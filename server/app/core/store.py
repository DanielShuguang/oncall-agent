"""运行态存储。

默认实现是 PostgreSQL：事件先落库、再推送（R2），`runs` 的汇总字段由事件
投影得到（docs/02 §3）。内存实现只用于测试与显式 `ONCALL_STORE_BACKEND=memory`，
**不做静默降级** —— 库挂了要让人看见，不能悄悄写内存然后重启丢数据。

`seq` 用「锁 run 行 + MAX(seq)+1」在同一事务内生成：单 run 的写入是串行的，
比时间戳排序可靠（R7）；并发量级（一个 run 一条流）不值得为每 run 建序列。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import and_, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.models.run import Run
from app.models.run import RunEvent as RunEventRow
from app.models.session_hidden import HiddenSession as HiddenSessionRow
from app.models.session_restore_audit import SessionRestoreAudit as SessionRestoreAuditRow
from app.models.session_title import SessionTitle as SessionTitleRow
from app.schemas.event import EventType, RunEvent, RunStatus
from app.schemas.failure import FailureCategory, categorize

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings

log = get_logger(__name__)


class RunNotFoundError(LookupError):
    """run_id 不存在。API 层翻译成 404，不要吞掉。"""


@dataclass
class RunRecord:
    run_id: str
    user_id: str
    session_id: str
    input: str
    status: str = RunStatus.RUNNING.value
    intent: str | None = None
    model: str | None = None
    output: str | None = None
    step_count: int = 0
    max_steps: int = 12
    token_in: int = 0
    token_out: int = 0
    cost_cents: int = 0
    error_code: str | None = None
    failure_category: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    #: 事件已被保留策略清理的时间（ADR-0021）；有值表示回放不可用，但 run 摘要仍在
    events_pruned_at: datetime | None = None
    #: 正文（`input`/`output`）已被保留策略清空的时间（ADR-0023）；有值表示只剩摘要
    content_pruned_at: datetime | None = None
    #: 回答引用过的知识库文档 id（ADR-0022）；读回放时按当前可见性重新校验
    cited_document_ids: list[str] = field(default_factory=list)
    #: 回答引用快照（ADR-0031）；正文被保留策略清空时一并清空（ADR-0023）
    citations: list[dict[str, Any]] = field(default_factory=list)
    event_count: int = 0


@dataclass(frozen=True)
class PrunedEvents:
    """一次事件清理的结果（ADR-0021）。

    `run_ids` 是**真正**被清理的 run（dry-run 时是候选）；`deleted` 是删除的事件行数，
    dry-run 不数行数（0），避免为了预览再扫一遍事件表。
    """

    run_ids: list[str]
    deleted: int = 0


@dataclass(frozen=True)
class PrunedContents:
    """一次 run 正文清理的结果（ADR-0023）。

    `run_ids` 是**真正**被清空正文的 run（dry-run 时是候选）；清理不改事件，
    所以没有「删了多少行」的计数，运维看的是场次。
    """

    run_ids: list[str]


@dataclass(frozen=True)
class SessionRestoreAuditRecord:
    """一次已移除会话恢复的审计快照（ADR-0059）。

    `session_ids` 只含真正恢复的 id，按请求顺序；`requested_count` 是去重后的
    请求数。没有恢复任何会话的操作不落审计行。
    """

    audit_id: str
    user_id: str
    session_ids: tuple[str, ...]
    requested_count: int
    restored_count: int
    restored_at: datetime


@dataclass(frozen=True)
class SessionRestoreAuditDayStats:
    """一天内的恢复活动（ADR-0065）；`day` 是 UTC 自然日。"""

    day: date
    restores: int
    sessions: int


@dataclass(frozen=True)
class SessionRestoreAuditStats:
    """窗口内的恢复审计汇总（ADR-0065）。

    `restores` 是操作次数（审计行数），`sessions` 是真正恢复的会话数之和；
    `users` 是去重后的操作者数。`daily` 只含有操作的 UTC 自然日，不补零。
    """

    since: datetime
    until: datetime
    restores: int
    users: int
    sessions: int
    daily: tuple[SessionRestoreAuditDayStats, ...] = ()


@dataclass(frozen=True)
class RunContentState:
    """回放读路径要的两个事实（ADR-0022 / ADR-0023），一次查询取回。

    分开查会让每秒轮询的事件补拉多一次往返；而这两件事必须**同时**看到，
    否则过期清理与权限回收会给出互相矛盾的标记。
    """

    cited_document_ids: list[str]
    content_pruned_at: datetime | None = None


@dataclass(frozen=True)
class StaleRun:
    """超过阈值没有任何事件的 running run（ADR-0017）。

    只给运维回收用；正常读写路径不依赖它。`last_event_at` 在没有事件时回退到
    `started_at`，覆盖「建完 run 还没写 run.started 就崩了」的情况。
    """

    run_id: str
    user_id: str
    started_at: datetime
    last_event_at: datetime


@dataclass(frozen=True)
class RunTurn:
    """已结束的一轮问答（ADR-0020 多轮上下文用）。

    只取用户输入与最终回答这两段投影，不读事件流：多轮上下文是「上一轮说了什么」，
    不是「上一轮调了哪些工具」。工具结果、审批载荷不进上下文，避免跨轮的旧证据混进答案。
    """

    query: str
    answer: str
    #: 这一轮回答引用过的文档（ADR-0022）；历史里要先按当前可见性过滤再喂给模型
    cited_document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionSummary:
    """一个会话的聚合摘要（ADR-0030）。

    会话不是独立实体：它由 `runs.session_id` 投影出来，排序用最近一次 run 的
    `started_at`。标题优先取用户自定义标题（ADR-0040），否则取**最早一条非空
    input**——正文被保留策略清空后为 None，前端显示「无标题」而不是让整个会话消失。
    """

    session_id: str
    title: str | None
    run_count: int
    started_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HiddenSessionSummary:
    """从列表移除的会话（ADR-0041 / ADR-0043）。

    只给「已移除」视图用：标题口径与 `SessionSummary` 一致（自定义标题优先，
    否则最早一条非空 input），时间取移除时间而不是最近活动时间。
    """

    session_id: str
    title: str | None
    run_count: int
    hidden_at: datetime


def _matches_session_query(needle: str, *candidates: str | None) -> bool:
    """会话搜索：任一候选标题包含 `needle`（调用方已 lower）。"""
    return any(candidate is not None and needle in candidate.lower() for candidate in candidates)


@dataclass(frozen=True)
class RunPatch:
    """事件对 runs 汇总字段的投影。None 表示该字段不更新。"""

    status: str | None = None
    finished_at: datetime | None = None
    output: str | None = None
    error_code: str | None = None
    failure_category: str | None = None
    model: str | None = None
    max_steps: int | None = None
    step_count: int | None = None
    token_in: int | None = None
    token_out: int | None = None
    cost_cents: int | None = None
    #: `message.completed` 的引用快照（ADR-0022）；空列表表示「这轮没有引用」，
    #: None 表示「这次事件不改这个字段」
    cited_document_ids: list[str] | None = None
    #: 给历史会话还原角标用的完整快照（ADR-0031）；与 id 列表同一次事件写入
    citations: list[dict[str, Any]] | None = None


_TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.INTERRUPTED.value,
}


def build_run_patch(event_type: EventType, payload: dict[str, Any], at: datetime) -> RunPatch:
    """把事件翻译成 runs 的字段补丁。

    只做「事件 → 当前态」的机械投影，不判断业务对错；审批超时等语义由
    发事件的 runtime 决定（W3）。
    """
    if event_type is EventType.RUN_STARTED:
        model = payload.get("model")
        return RunPatch(
            status=RunStatus.RUNNING.value,
            model=model if isinstance(model, str) else None,
            max_steps=_int_or_none(payload.get("max_steps")),
        )

    if event_type is EventType.APPROVAL_REQUIRED:
        return RunPatch(status=RunStatus.AWAITING_APPROVAL.value)

    if event_type is EventType.APPROVAL_RESOLVED:
        decision = payload.get("status")
        if decision == "approved":
            return RunPatch(status=RunStatus.RUNNING.value)
        if decision == "expired":
            return RunPatch(
                status=RunStatus.FAILED.value,
                finished_at=at,
                error_code="APPROVAL_TIMEOUT",
                failure_category=FailureCategory.APPROVAL.value,
            )
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code="APPROVAL_REJECTED",
            failure_category=FailureCategory.APPROVAL.value,
        )

    if event_type is EventType.MESSAGE_COMPLETED:
        text = payload.get("text")
        return RunPatch(
            output=text if isinstance(text, str) else None,
            cited_document_ids=_cited_document_ids(payload.get("citations")),
            citations=_citation_snapshot(payload.get("citations")),
        )

    if event_type is EventType.RUN_COMPLETED:
        return RunPatch(
            status=RunStatus.COMPLETED.value,
            finished_at=at,
            step_count=_int_or_none(payload.get("steps")),
            token_in=_int_or_none(payload.get("token_in")),
            token_out=_int_or_none(payload.get("token_out")),
            cost_cents=_int_or_none(payload.get("cost_cents")),
        )

    if event_type is EventType.RUN_FAILED:
        code = payload.get("error_code")
        error_code = code if isinstance(code, str) else "UNKNOWN"
        category = payload.get("category")
        if not isinstance(category, str):
            category = categorize(error_code).value
        else:
            try:
                category = FailureCategory(category).value
            except ValueError:
                category = categorize(error_code).value
        return RunPatch(
            status=RunStatus.FAILED.value,
            finished_at=at,
            error_code=error_code,
            failure_category=category,
        )

    return RunPatch()


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


#: 引用快照上限：一次回答的引用本来就来自 top_k；这里只防脏 payload 把 JSONB 撑大
MAX_CITED_DOCUMENTS = 50
#: 快照里的文本字段上限：title/heading 只用于角标与预览标题，snippet 只用于兜底展示；
#: 事件表里的 JSON 不能假设一定来自 runtime，超长字符串同样要截断
MAX_CITATION_TITLE = 200
MAX_CITATION_SNIPPET = 500


def _cited_document_ids(raw: Any) -> list[str] | None:
    """从 `message.completed.citations` 里抽文档 id（ADR-0022）。

    不是数组就返回 None（这次事件不改字段）；空数组返回 `[]`（这轮明确没有引用）。
    id 只认非空字符串，去重保序并截断到上限：payload 是事件表里的 JSON，
    不能假设它一定来自 runtime。
    """
    if not isinstance(raw, list):
        return None
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id")
        if not isinstance(document_id, str) or not document_id or document_id in ids:
            continue
        ids.append(document_id)
        if len(ids) >= MAX_CITED_DOCUMENTS:
            break
    return ids


def _citation_snapshot(raw: Any) -> list[dict[str, Any]] | None:
    """从 `message.completed.citations` 抽可回放的快照（ADR-0031）。

    与 `_cited_document_ids` 不同：这里要保住角标与预览所需的字段。类型不对的
    字段退回默认值而不是整条丢弃；没有 `document_id` 的条目无法预览，直接跳过；
    文本字段超长截断，防止脏 payload 把 JSONB 撑大。非数组返回 None（这次事件
    不改字段），空数组返回 `[]`（这轮明确没有引用）。
    """
    if not isinstance(raw, list):
        return None
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            continue
        title = item.get("title")
        heading = item.get("heading")
        snippet = item.get("snippet")
        page = item.get("page")
        citation: dict[str, Any] = {
            "chunk_id": _as_int(item.get("chunk_id")),
            "document_id": document_id,
            "ord": _as_int(item.get("ord")),
            "title": _clip_text(title, MAX_CITATION_TITLE),
            "snippet": _clip_text(snippet, MAX_CITATION_SNIPPET),
        }
        if isinstance(heading, str):
            citation["heading"] = _clip_text(heading, MAX_CITATION_TITLE)
        if isinstance(page, int) and not isinstance(page, bool):
            citation["page"] = page
        items.append(citation)
        if len(items) >= MAX_CITED_DOCUMENTS:
            break
    return items


def _clip_text(value: Any, limit: int) -> str:
    """非字符串退空串，超长按上限截断；保的是「不会把脏 payload 写进库」。"""
    return value[:limit] if isinstance(value, str) else ""


def _as_int(value: Any) -> int:
    """JSON 里的 bool 也是 int 子类；引用字段只认真正的整数。"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _apply_patch(record: RunRecord, patch: RunPatch) -> None:
    for name in patch.__dataclass_fields__:
        value = getattr(patch, name)
        if value is not None:
            setattr(record, name, value)


class RunStore(Protocol):
    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        """创建 run；`client_msg_id` 命中时返回已存在的 run 且 created=False。"""
        ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        """幂等命中查询；限流拒绝前用它判断是否只是重放已有 run。"""
        ...

    async def status(self, run_id: str) -> str | None: ...

    async def owner(self, run_id: str) -> str | None:
        """run 的 user_id；不存在返回 None。路由层做归属校验用，不要为此跑 COUNT。"""
        ...

    async def content_state(self, run_id: str) -> RunContentState | None:
        """回放要用的内容状态（引用快照 + 是否已过保留期）；run 不存在返回 None。

        回放与详情在读取时要用引用快照按**当前**可见性重新校验（ADR-0022），
        并区分正文是否已被保留策略清空（ADR-0023）。不复用 `get()`：那个会
        顺便 COUNT 事件，而被每秒轮询的事件补拉不该付这个代价。
        """
        ...

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        """追加事件并更新 runs 汇总字段，同一事务内完成。"""
        ...

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]: ...

    async def events_for_runs(
        self, run_ids: Sequence[str], *, limit_per_run: int = 500
    ) -> dict[str, list[RunEvent]]:
        """一次取多个 run 的前 N 条事件（ADR-0036 会话历史批量回放）。

        返回按 `run_id` 分组、组内按 `seq` 升序；只包含入参里存在的 run。
        没有这个方法时，打开 20 轮会话要发 20 次事件查询。
        """
        ...

    async def set_status(
        self, run_id: str, status: str, *, error_code: str | None = None
    ) -> None: ...

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        """`running` 且最后一条事件（没有事件时用 `started_at`）早于 `older_than`。"""
        ...

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        """原子地把「仍然 running 且确实过期」的 run 追加 `run.failed`。

        返回是否真的写入。状态检查、过期检查与事件写入在同一事务里完成，
        多副本同时回收也只会有一次成功；刚有新事件或已进入终态的 run 不会被误杀。
        """
        ...

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[RunRecord]:
        """按 started_at 倒序；`(before_started_at, before_run_id)` 是上一页游标。"""
        ...

    async def list_sessions(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_updated_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[SessionSummary]:
        """按 `session_id` 聚合该用户最近的会话，按最近一次 run 倒序（ADR-0030）。

        会话没有独立表：标题取最早一条非空 `input`，计数与时间来自 runs 投影。
        没有 run 的会话不存在，因此不需要清理任务。`(before_updated_at,
        before_session_id)` 是上一页游标（ADR-0033）；新 run 会把会话移到更前，
        翻页途中可能重复或跳过一页，刷新列表即重置。

        `query` 只按投影标题做大小写不敏感的子串匹配（ADR-0039）：不搜回答正文、
        不搜被保留策略清空的历史；标题来自首条非空问题，不是最后一轮。
        自定义标题（ADR-0040）覆盖展示标题，搜索同时匹配自定义标题与首条问题。
        """
        ...

    async def rename_session(self, *, user_id: str, session_id: str, title: str | None) -> bool:
        """设置或清除会话的自定义标题（ADR-0040）。

        `title=None` 表示恢复默认（首条非空问题）。返回 False 表示这个用户没有
        该会话（没有任何 run）——调用方翻成 404，不泄露别人的会话是否存在。
        """
        ...

    async def hide_session(self, *, user_id: str, session_id: str) -> bool:
        """把这个会话从该用户的会话列表中移除（ADR-0041，软移除）。

        只写一行 `hidden_sessions`；`runs`、事件、审批与标题行都保留，保留清理
        仍按时间执行。返回 False 表示这个用户没有该会话（没有任何 run），
        调用方翻成 404。重复移除是幂等的，仍返回 True。
        """
        ...

    async def list_hidden_sessions(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before_hidden_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[HiddenSessionSummary]:
        """列出该用户从列表移除的会话，按移除时间倒序（ADR-0043）。

        标题与计数仍从 runs 投影；没有 run 的残留行不返回。只用于「已移除」
        视图，普通列表与搜索始终排除这些会话（ADR-0041）。

        `(before_hidden_at, before_session_id)` 是上一页 keyset 游标（ADR-0047）。
        `query` 与主列表同口径：大小写不敏感、同时匹配自定义标题与首条问题，
        不搜回答正文。移除时间相同的会话按 `session_id` 倒序保证稳定。
        """
        ...

    async def unhide_session(self, *, user_id: str, session_id: str) -> bool:
        """把会话恢复到该用户的列表（ADR-0043）。

        删除 `hidden_sessions` 行；返回 False 表示这个用户没有该会话或它本来
        就没有被移除——调用方翻成 404，不泄露别人的会话是否存在。
        """
        ...

    async def unhide_sessions(self, *, user_id: str, session_ids: Sequence[str]) -> set[str]:
        """批量恢复已移除的会话（ADR-0049/0055）。

        一次删除该用户名下多个 `hidden_sessions` 行，返回真正删掉的 session_id。
        不存在、属于别人、或本来就没移除的 id 不会出现在结果里：批量操作是
        部分成功语义，不因一个 id 失效让整批失败。`session_ids` 由 API 去重并
        限制长度；返回集合用于逐条结果，不保证顺序。

        有会话真正恢复时，同一事务内写一条 `session_restore_audits`（ADR-0059）：
        审计与删除必须原子，不能恢复成功而审计丢失。
        """
        ...

    async def list_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> list[SessionRestoreAuditRecord]:
        """按 `(restored_at, id)` 倒序列出审计（ADR-0059/0060/0061/0067）。

        `user_id`/`session_id` 都是可选过滤：前者按操作者，后者按「这个会话
        是否在本次批量恢复里被真正恢复」；`session_id` 命中 `session_ids` 数组
        的任一元素即可。`restored_from`/`restored_to` 是闭区间时间过滤，由 API
        把 UTC 日期范围换算后传入。`before=(restored_at, audit_id)` 是 keyset
        游标，只返回严格更早的记录。表只追加，默认保留 365 天由
        `RetentionSweeper` 清理。
        """
        ...

    async def count_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
    ) -> int:
        """按与列表相同的过滤条件统计恢复审计总数（ADR-0064/0067）。

        只服务管理端首屏 total；与 `list_session_restore_audits` 是两次查询，
        不是同一快照。`user_id` 走 `(user_id, restored_at)` 索引，`session_id`
        走迁移 0020 的 JSONB GIN；都不带时是全表 COUNT。
        """
        ...

    async def session_restore_audit_stats(
        self,
        *,
        since: datetime,
        until: datetime,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionRestoreAuditStats:
        """窗口 `[since, until]` 内的恢复审计汇总（ADR-0065/0066）。

        只统计 `restored_at` 落在窗口内的审计行；`sessions` 用
        `restored_count` 求和，而不是 JSONB 数组长度。`daily` 按 UTC 自然日
        稀疏聚合，空日不补零。窗口由调用方计算，store 不做时区转换。
        `user_id`/`session_id` 与列表同一过滤口径；都不带时是全局统计。
        """
        ...

    async def prune_session_restore_audits(
        self, *, restored_before: datetime, limit: int = 200, dry_run: bool = False
    ) -> int:
        """删除 `restored_at` 早于阈值的恢复审计（ADR-0059），返回条数。

        dry-run 只数候选、不删除；审计行删除后不可恢复，但会话恢复本身已经完成。
        """
        ...

    async def list_runs_without_citations(self, *, limit: int = 100) -> list[RunRecord]:
        """列出仍没有引用快照、且事件与正文都还保留着的 run（ADR-0042 回填用）。

        只选 `citations == []`、`content_pruned_at is None`、`events_pruned_at is None`
        且 `output is not None` 的 run；按 `started_at, run_id` 升序，重复执行时
        优先处理更早的数据。回填是 opt-in 的运维动作，不在请求路径上。
        """
        ...

    async def set_citations(self, run_id: str, citations: list[dict[str, Any]]) -> bool:
        """仅当 run 的引用快照仍为空时写入（ADR-0042）。

        返回 False 表示 run 不存在、已经有快照（已回填/并发写入），或正文/事件
        刚被保留清理（ADR-0023）——后一种情况写回会把快照写得比正文久。
        同时把 `cited_document_ids` 合并进 run，保证 ADR-0022 的可见性回收对
        回填出来的旧数据同样生效。调用方不应把 False 当异常。
        """
        ...

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        """同一用户同一会话里**已经有回答**的最近 `limit` 轮，按时间正序返回。

        只认 `runs.output` 非空：拒答也是回答（"知识库里没有"本身要进上下文），
        但还没走完的 run（挂起审批 / 正在跑 / 中断）没有 output，不能当成历史，
        否则用户会看到模型"记得"一句它从未说过的话。
        """
        ...

    async def prune_events(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedEvents:
        """清理已结束（completed/failed/interrupted）且 `finished_at` 早于阈值的 run 事件。

        以 **run 为单位整场删除**，而不是按事件时间逐条删：只删一半会让回放从中间
        开始，前端归约器会得到一个没有 run.started 的时间线。删除事件与写
        `runs.events_pruned_at` 标记在同一事务内完成，多副本同时清理也只会有一次效果。
        非终态 run 永远不清理（等待审批的 run 可能长时间没有新事件）。
        """
        ...

    async def prune_contents(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedContents:
        """清空已结束（completed/failed/interrupted）且早于阈值的 run 的正文（ADR-0023）。

        只清 `input`（置空串）与 `output`（置 NULL），并写 `content_pruned_at`；
        状态、计量、失败归因与引用快照都保留——运行列表、成本口径和失败率靠它们。
        事件不动：保留天数要求正文不短于事件（`ONCALL_RUN_CONTENT_RETENTION_DAYS
        >= ONCALL_EVENT_RETENTION_DAYS`），所以走到这里时回放早已不可用。
        非终态 run 永远不清（等待审批的 run 可能长时间没有新事件）。
        """
        ...


class InMemoryRunStore:
    """测试与 demo 用。事件只在进程内，重启即丢。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[RunEvent]] = {}
        self._client_index: dict[tuple[str, str], str] = {}
        #: 用户改过的显示标题；没有行时回落到首条非空 input（ADR-0040）
        self._session_titles: dict[tuple[str, str], str] = {}
        #: 用户从列表移除的会话（ADR-0041）；run/事件仍保留
        #: 从列表移除的会话 → 移除时间（ADR-0041/0043）；行仍在 runs 里
        self._hidden_sessions: dict[tuple[str, str], datetime] = {}
        #: 恢复审计，按发生顺序追加（ADR-0059）；列表时反向读出
        self._session_restore_audits: list[SessionRestoreAuditRecord] = []
        self._lock = asyncio.Lock()
        self._started_at: datetime | None = None

    def _next_started_at(self) -> datetime:
        """单调递增的创建时间。

        Windows 的 `datetime.now()` 分辨率约 1ms：连续创建的两个 run 会拿到相同时间，
        而排序/分页的次序化依赖 `started_at`（R7 的时间口径）。内存实现里补一个微秒，
        让「先创建的排在前面」成为确定行为，而不是靠 uuid 随机序当第二排序键。
        """
        now = datetime.now(UTC)
        if self._started_at is not None and now <= self._started_at:
            now = self._started_at + timedelta(microseconds=1)
        self._started_at = now
        return now

    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        rid = str(uuid.UUID(run_id))
        client_msg_id = client_msg_id or None
        key = (user_id, client_msg_id) if client_msg_id else None
        async with self._lock:
            if key is not None and key in self._client_index:
                existing = self._client_index[key]
                return self._runs[existing], False
            record = RunRecord(
                run_id=rid,
                user_id=user_id,
                session_id=session_id,
                input=message,
                model=model,
                max_steps=max_steps,
                started_at=self._next_started_at(),
            )
            self._runs[rid] = record
            self._events[rid] = []
            if key is not None:
                self._client_index[key] = rid
            return record, True

    async def get(self, run_id: str) -> RunRecord | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        if record is not None:
            record.event_count = len(self._events[rid])
        return record

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        rid = self._client_index.get((user_id, client_msg_id))
        if rid is None:
            return None
        record = self._runs.get(rid)
        if record is not None:
            record.event_count = len(self._events[rid])
        return record

    async def status(self, run_id: str) -> str | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        return record.status if record is not None else None

    async def owner(self, run_id: str) -> str | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        return record.user_id if record is not None else None

    async def content_state(self, run_id: str) -> RunContentState | None:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return None
        record = self._runs.get(rid)
        if record is None:
            return None
        return RunContentState(
            cited_document_ids=list(record.cited_document_ids),
            content_pruned_at=record.content_pruned_at,
        )

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            return self._append_locked(rid, event_type, payload)

    def _append_locked(
        self, rid: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        record = self._runs.get(rid)
        if record is None:
            raise RunNotFoundError(rid)
        now = datetime.now(UTC)
        event = RunEvent(
            seq=len(self._events[rid]) + 1,
            run_id=rid,
            type=event_type,
            ts=now,
            payload=payload or {},
        )
        self._events[rid].append(event)
        record.event_count = len(self._events[rid])
        _apply_patch(record, build_run_patch(event_type, event.payload, now))
        if event_type is EventType.STEP_COMPLETED:
            # 失败 run 也需要“跑了几步”的口径；run.completed 会覆盖为准确值
            record.step_count += 1
        return event

    def _last_activity_locked(self, rid: str) -> datetime:
        events = self._events.get(rid) or []
        return events[-1].ts if events else self._runs[rid].started_at

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return []
        return [e for e in self._events.get(rid, []) if e.seq > after_seq][:limit]

    async def events_for_runs(
        self, run_ids: Sequence[str], *, limit_per_run: int = 500
    ) -> dict[str, list[RunEvent]]:
        grouped: dict[str, list[RunEvent]] = {}
        for run_id in run_ids:
            try:
                rid = str(uuid.UUID(run_id))
            except ValueError:
                continue
            events = self._events.get(rid)
            if events:
                grouped[run_id] = events[:limit_per_run]
        return grouped

    async def set_status(self, run_id: str, status: str, *, error_code: str | None = None) -> None:
        rid = str(uuid.UUID(run_id))
        async with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunNotFoundError(run_id)
            # 终态是事件流的结果，不能被断连收尾覆盖（run.completed 后断开很常见）
            if record.status in _TERMINAL_STATUSES:
                return
            record.status = status
            if error_code is not None:
                record.error_code = error_code
                record.failure_category = categorize(error_code).value
            if status in _TERMINAL_STATUSES:
                record.finished_at = datetime.now(UTC)

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        async with self._lock:
            items: list[StaleRun] = []
            for rid, record in self._runs.items():
                if record.status != RunStatus.RUNNING.value:
                    continue
                last = self._last_activity_locked(rid)
                if last >= older_than:
                    continue
                items.append(
                    StaleRun(
                        run_id=rid,
                        user_id=record.user_id,
                        started_at=record.started_at,
                        last_event_at=last,
                    )
                )
        items.sort(key=lambda item: item.started_at)
        return items[:limit]

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        try:
            rid = str(uuid.UUID(run_id))
        except ValueError:
            return False
        async with self._lock:
            record = self._runs.get(rid)
            if record is None or record.status != RunStatus.RUNNING.value:
                return False
            if self._last_activity_locked(rid) >= older_than:
                return False
            self._append_locked(rid, EventType.RUN_FAILED, payload)
            return True

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[RunRecord]:
        rows = [record for record in self._runs.values() if record.user_id == user_id]
        if status:
            rows = [record for record in rows if record.status == status]
        if session_id is not None:
            rows = [record for record in rows if record.session_id == session_id]
        rows.sort(key=lambda record: (record.started_at, record.run_id), reverse=True)
        if before_started_at is not None and before_run_id is not None:
            rows = [
                record
                for record in rows
                if (record.started_at, record.run_id) < (before_started_at, before_run_id)
            ]
        return rows[:limit]

    async def list_sessions(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_updated_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[SessionSummary]:
        grouped: dict[str, list[RunRecord]] = {}
        for record in self._runs.values():
            if (
                record.user_id == user_id
                and (user_id, record.session_id) not in self._hidden_sessions
            ):
                grouped.setdefault(record.session_id, []).append(record)

        summaries: list[SessionSummary] = []
        #: 首条非空 input 的原文；搜索同时匹配它和自定义标题（ADR-0040）
        generated: dict[str, str | None] = {}
        for session_id, records in grouped.items():
            records.sort(key=lambda record: (record.started_at, record.run_id))
            first_input = next((record.input for record in records if record.input.strip()), None)
            generated[session_id] = first_input
            custom = self._session_titles.get((user_id, session_id))
            summaries.append(
                SessionSummary(
                    session_id=session_id,
                    title=custom if custom is not None else first_input,
                    run_count=len(records),
                    started_at=records[0].started_at,
                    updated_at=records[-1].started_at,
                )
            )
        if query:
            needle = query.lower()
            summaries = [
                item
                for item in summaries
                if _matches_session_query(needle, item.title, generated.get(item.session_id))
            ]
        summaries.sort(key=lambda item: (item.updated_at, item.session_id), reverse=True)
        if before_updated_at is not None and before_session_id is not None:
            summaries = [
                item
                for item in summaries
                if (item.updated_at, item.session_id) < (before_updated_at, before_session_id)
            ]
        return summaries[:limit]

    async def rename_session(self, *, user_id: str, session_id: str, title: str | None) -> bool:
        async with self._lock:
            # 只有「这个用户确实有这个会话」才允许改；别人的会话与不存在的会话
            # 在调用方统一表现为 False → 404，不泄露存在性。
            if not any(
                record.user_id == user_id and record.session_id == session_id
                for record in self._runs.values()
            ):
                return False
            if title is None:
                self._session_titles.pop((user_id, session_id), None)
            else:
                self._session_titles[(user_id, session_id)] = title
            return True

    async def hide_session(self, *, user_id: str, session_id: str) -> bool:
        async with self._lock:
            if not any(
                record.user_id == user_id and record.session_id == session_id
                for record in self._runs.values()
            ):
                return False
            # 重复移除保留第一次的 hidden_at，与 PG 的 on_conflict_do_nothing 一致
            self._hidden_sessions.setdefault((user_id, session_id), datetime.now(UTC))
            return True

    async def list_hidden_sessions(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before_hidden_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[HiddenSessionSummary]:
        async with self._lock:
            by_session: dict[str, list[RunRecord]] = {}
            for record in self._runs.values():
                if record.user_id == user_id:
                    by_session.setdefault(record.session_id, []).append(record)
            items: list[HiddenSessionSummary] = []
            #: 首条非空 input 的原文；搜索同时匹配它和自定义标题（ADR-0040/0047）
            generated: dict[str, str | None] = {}
            for (hidden_user, session_id), hidden_at in self._hidden_sessions.items():
                if hidden_user != user_id:
                    continue
                records = by_session.get(session_id)
                if not records:
                    continue
                records.sort(key=lambda record: (record.started_at, record.run_id))
                first_input = next(
                    (record.input for record in records if record.input.strip()), None
                )
                generated[session_id] = first_input
                custom = self._session_titles.get((user_id, session_id))
                items.append(
                    HiddenSessionSummary(
                        session_id=session_id,
                        title=custom if custom is not None else first_input,
                        run_count=len(records),
                        hidden_at=hidden_at,
                    )
                )
            if query:
                needle = query.lower()
                items = [
                    item
                    for item in items
                    if _matches_session_query(needle, item.title, generated.get(item.session_id))
                ]
            items.sort(key=lambda item: (item.hidden_at, item.session_id), reverse=True)
            if before_hidden_at is not None and before_session_id is not None:
                items = [
                    item
                    for item in items
                    if (item.hidden_at, item.session_id) < (before_hidden_at, before_session_id)
                ]
            return items[:limit]

    async def unhide_session(self, *, user_id: str, session_id: str) -> bool:
        return bool(await self.unhide_sessions(user_id=user_id, session_ids=[session_id]))

    async def unhide_sessions(self, *, user_id: str, session_ids: Sequence[str]) -> set[str]:
        unique_ids = list(dict.fromkeys(session_ids))
        if not unique_ids:
            return set()
        async with self._lock:
            restored = {
                session_id
                for session_id in unique_ids
                if self._hidden_sessions.pop((user_id, session_id), None) is not None
            }
            if restored:
                # 按请求顺序记录真正恢复的 id，和 API 逐条结果口径一致
                ordered = [session_id for session_id in unique_ids if session_id in restored]
                self._session_restore_audits.append(
                    SessionRestoreAuditRecord(
                        audit_id=str(uuid.uuid4()),
                        user_id=user_id,
                        session_ids=tuple(ordered),
                        requested_count=len(unique_ids),
                        restored_count=len(ordered),
                        restored_at=datetime.now(UTC),
                    )
                )
            return restored

    async def list_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> list[SessionRestoreAuditRecord]:
        async with self._lock:
            records = [
                record
                for record in self._session_restore_audits
                if (user_id is None or record.user_id == user_id)
                and (session_id is None or session_id in record.session_ids)
                and (restored_from is None or record.restored_at >= restored_from)
                and (restored_to is None or record.restored_at <= restored_to)
            ]
            records.sort(key=lambda record: (record.restored_at, record.audit_id), reverse=True)
            if before is not None:
                records = [
                    record for record in records if (record.restored_at, record.audit_id) < before
                ]
            return records[:limit]

    async def count_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
    ) -> int:
        async with self._lock:
            return sum(
                1
                for record in self._session_restore_audits
                if (user_id is None or record.user_id == user_id)
                and (session_id is None or session_id in record.session_ids)
                and (restored_from is None or record.restored_at >= restored_from)
                and (restored_to is None or record.restored_at <= restored_to)
            )

    async def session_restore_audit_stats(
        self,
        *,
        since: datetime,
        until: datetime,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionRestoreAuditStats:
        async with self._lock:
            records = [
                record
                for record in self._session_restore_audits
                if since <= record.restored_at <= until
                and (user_id is None or record.user_id == user_id)
                and (session_id is None or session_id in record.session_ids)
            ]
        per_day: dict[date, list[int]] = {}
        users: set[str] = set()
        sessions = 0
        for record in records:
            users.add(record.user_id)
            sessions += record.restored_count
            day = record.restored_at.astimezone(UTC).date()
            bucket = per_day.setdefault(day, [0, 0])
            bucket[0] += 1
            bucket[1] += record.restored_count
        return SessionRestoreAuditStats(
            since=since,
            until=until,
            restores=len(records),
            users=len(users),
            sessions=sessions,
            daily=tuple(
                SessionRestoreAuditDayStats(day=day, restores=values[0], sessions=values[1])
                for day, values in sorted(per_day.items())
            ),
        )

    async def prune_session_restore_audits(
        self, *, restored_before: datetime, limit: int = 200, dry_run: bool = False
    ) -> int:
        async with self._lock:
            candidates = sorted(
                (
                    record
                    for record in self._session_restore_audits
                    if record.restored_at < restored_before
                ),
                key=lambda record: record.restored_at,
            )[:limit]
            if dry_run or not candidates:
                return len(candidates)
            expired = {record.audit_id for record in candidates}
            self._session_restore_audits = [
                record for record in self._session_restore_audits if record.audit_id not in expired
            ]
            return len(candidates)

    async def list_runs_without_citations(self, *, limit: int = 100) -> list[RunRecord]:
        async with self._lock:
            candidates = [
                record
                for record in self._runs.values()
                if not record.citations
                and record.content_pruned_at is None
                and record.events_pruned_at is None
                and record.output is not None
            ]
            candidates.sort(key=lambda record: (record.started_at, record.run_id))
            return candidates[:limit]

    async def set_citations(self, run_id: str, citations: list[dict[str, Any]]) -> bool:
        async with self._lock:
            record = self._runs.get(run_id)
            if (
                record is None
                or record.citations
                or record.content_pruned_at is not None
                or record.events_pruned_at is not None
                or record.output is None
            ):
                return False
            # 与 PG 条件写同口径：事件投影/保留清理刚改过的行不能覆盖
            record.citations = [dict(item) for item in citations]
            # 旧 run 可能没有 cited_document_ids；补上才能走 ADR-0022 的可见性回收
            new_ids = _cited_document_ids(citations) or []
            record.cited_document_ids = list(dict.fromkeys([*record.cited_document_ids, *new_ids]))
            return True

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        rows = [
            record
            for record in self._runs.values()
            if record.user_id == user_id
            and record.session_id == session_id
            and record.run_id != exclude_run_id
            and (record.output or "").strip()
        ]
        rows.sort(key=lambda record: (record.started_at, record.run_id), reverse=True)
        newest = rows[:limit]
        newest.reverse()
        return [
            RunTurn(
                query=record.input,
                answer=record.output or "",
                cited_document_ids=tuple(record.cited_document_ids),
            )
            for record in newest
        ]

    async def prune_events(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedEvents:
        async with self._lock:
            candidates = [
                (record.finished_at, record.run_id)
                for record in self._runs.values()
                if record.status in _TERMINAL_STATUSES
                and record.events_pruned_at is None
                and record.finished_at is not None
                and record.finished_at < finished_before
            ]
            candidates.sort()
            run_ids = [run_id for _, run_id in candidates[:limit]]
            if dry_run:
                return PrunedEvents(run_ids=run_ids)

            pruned_at = datetime.now(UTC)
            deleted = 0
            for run_id in run_ids:
                deleted += len(self._events.get(run_id) or [])
                self._events[run_id] = []
                record = self._runs[run_id]
                record.events_pruned_at = pruned_at
                record.event_count = 0
            return PrunedEvents(run_ids=run_ids, deleted=deleted)

    async def prune_contents(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedContents:
        async with self._lock:
            candidates = [
                (record.finished_at, record.run_id)
                for record in self._runs.values()
                if record.status in _TERMINAL_STATUSES
                and record.content_pruned_at is None
                and record.finished_at is not None
                and record.finished_at < finished_before
                # 已经空了的 run 不再算候选（与 Postgres 实现同口径）：
                # 否则 dry-run 会一直把它们列成「待清理」
                and (record.input or record.output is not None)
            ]
            candidates.sort()
            run_ids = [run_id for _, run_id in candidates[:limit]]
            if dry_run:
                return PrunedContents(run_ids=run_ids)

            pruned_at = datetime.now(UTC)
            for run_id in run_ids:
                record = self._runs[run_id]
                record.input = ""
                record.output = None
                # 引用片段属于回答内容：正文清空时一并清掉（ADR-0031）；
                # 文档 id 留着给权限回收判定（ADR-0022）
                record.citations = []
                record.content_pruned_at = pruned_at
            return PrunedContents(run_ids=run_ids)


async def append_event_in_session(
    session: AsyncSession,
    run_id: str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    """在调用方的事务里追加一条事件。

    审批决议要把 `approvals.status`、`approval.resolved` 和拒绝/超时的
    `run.failed` 写成一次提交（ADR-0016），所以事件写入必须能挂到外层事务上，
    不能像 `PostgresRunStore.append` 那样自己开事务。
    """
    rid = uuid.UUID(run_id)
    data = payload or {}
    # 行锁保证同一 run 的 seq 分配串行，避免 MAX(seq)+1 并发撞主键
    row = await session.scalar(select(Run).where(Run.id == rid).with_for_update())
    if row is None:
        raise RunNotFoundError(run_id)

    last_seq = await session.scalar(
        select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == rid)
    )
    seq = int(last_seq or 0) + 1
    now = datetime.now(UTC)
    session.add(
        RunEventRow(
            run_id=rid,
            seq=seq,
            type=event_type.value,
            payload=data,
            created_at=now,
        )
    )

    patch = build_run_patch(event_type, data, now)
    for name in patch.__dataclass_fields__:
        value = getattr(patch, name)
        if value is not None:
            setattr(row, name, value)
    if event_type is EventType.STEP_COMPLETED:
        # 失败 run 也需要“跑了几步”的口径；run.completed 会覆盖为准确值
        row.step_count += 1

    await session.flush()
    return RunEvent(seq=seq, run_id=str(rid), type=event_type, ts=now, payload=data)


class PostgresRunStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        session_id: str,
        message: str,
        client_msg_id: str | None = None,
        model: str | None = None,
        max_steps: int = 12,
    ) -> tuple[RunRecord, bool]:
        rid = uuid.UUID(run_id)
        client_msg_id = client_msg_id or None
        if client_msg_id:
            existing = await self.find_by_client_msg_id(user_id, client_msg_id)
            if existing is not None:
                return existing, False

        row = Run(
            id=rid,
            client_msg_id=client_msg_id,
            user_id=user_id,
            session_id=session_id,
            status=RunStatus.RUNNING.value,
            input=message,
            model=model,
            max_steps=max_steps,
            started_at=datetime.now(UTC),
        )
        async with self._sessionmaker() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # 并发重复提交：唯一约束兜底，回读先落库的那条
                await session.rollback()
                if client_msg_id:
                    existing = await self.find_by_client_msg_id(user_id, client_msg_id)
                    if existing is not None:
                        return existing, False
                raise
        return _record_from_row(row, event_count=0), True

    async def get(self, run_id: str) -> RunRecord | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            row = await session.get(Run, rid)
            if row is None:
                return None
            count = await session.scalar(
                select(func.count()).select_from(RunEventRow).where(RunEventRow.run_id == rid)
            )
        return _record_from_row(row, event_count=int(count or 0))

    async def status(self, run_id: str) -> str | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            return await session.scalar(select(Run.status).where(Run.id == rid))

    async def owner(self, run_id: str) -> str | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            return await session.scalar(select(Run.user_id).where(Run.id == rid))

    async def content_state(self, run_id: str) -> RunContentState | None:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(Run.cited_document_ids, Run.content_pruned_at).where(Run.id == rid)
                )
            ).first()
        if row is None:
            return None
        cited, pruned_at = row
        return RunContentState(
            cited_document_ids=list(cited or []),
            content_pruned_at=pruned_at,
        )

    async def append(
        self, run_id: str, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> RunEvent:
        async with self._sessionmaker() as session, session.begin():
            return await append_event_in_session(session, run_id, event_type, payload)

    async def events_after(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[RunEvent]:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return []
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(RunEventRow)
                    .where(RunEventRow.run_id == rid, RunEventRow.seq > after_seq)
                    .order_by(RunEventRow.seq)
                    .limit(limit)
                )
            ).all()
        events = [_event_from_row(row) for row in rows]
        return [event for event in events if event is not None]

    async def events_for_runs(
        self, run_ids: Sequence[str], *, limit_per_run: int = 500
    ) -> dict[str, list[RunEvent]]:
        uids: list[uuid.UUID] = []
        for run_id in run_ids:
            try:
                uids.append(uuid.UUID(run_id))
            except ValueError:
                continue
        if not uids:
            return {}
        # 每个 run 只取前 N 条：用窗口函数而不是对每个 run 单独 LIMIT，
        # 否则 20 轮历史又要退化成 20 次查询（ADR-0036）。
        ranked = (
            select(
                RunEventRow.run_id,
                RunEventRow.seq,
                func.row_number()
                .over(partition_by=RunEventRow.run_id, order_by=RunEventRow.seq)
                .label("rn"),
            )
            .where(RunEventRow.run_id.in_(uids))
            .subquery()
        )
        first_n = select(ranked.c.run_id, ranked.c.seq).where(ranked.c.rn <= limit_per_run)
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(RunEventRow)
                    .where(tuple_(RunEventRow.run_id, RunEventRow.seq).in_(first_n))
                    .order_by(RunEventRow.run_id, RunEventRow.seq)
                )
            ).all()
        grouped: dict[str, list[RunEvent]] = {}
        for row in rows:
            event = _event_from_row(row)
            if event is None:
                continue
            grouped.setdefault(str(row.run_id), []).append(event)
        return grouped

    async def set_status(self, run_id: str, status: str, *, error_code: str | None = None) -> None:
        rid = uuid.UUID(run_id)
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(Run, rid, with_for_update=True)
            if row is None:
                raise RunNotFoundError(run_id)
            # 不要用断连收尾覆盖已经落库的终态
            if row.status in _TERMINAL_STATUSES:
                return
            row.status = status
            if error_code is not None:
                row.error_code = error_code
                row.failure_category = categorize(error_code).value
            if status in _TERMINAL_STATUSES:
                row.finished_at = datetime.now(UTC)

    async def list_stale_runs(self, *, older_than: datetime, limit: int = 100) -> list[StaleRun]:
        last_event = (
            select(func.max(RunEventRow.created_at))
            .where(RunEventRow.run_id == Run.id)
            .scalar_subquery()
        )
        stmt = (
            select(Run, last_event)
            .where(Run.status == RunStatus.RUNNING.value)
            .where(func.coalesce(last_event, Run.started_at) < older_than)
            .order_by(Run.started_at)
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            StaleRun(
                run_id=str(row.id),
                user_id=row.user_id,
                started_at=row.started_at,
                last_event_at=last or row.started_at,
            )
            for row, last in rows
        ]

    async def fail_stale_run(
        self, run_id: str, *, older_than: datetime, payload: dict[str, Any]
    ) -> bool:
        try:
            rid = uuid.UUID(run_id)
        except ValueError:
            return False
        async with self._sessionmaker() as session, session.begin():
            # 锁住 run 行后再检查：与 append 的 seq 分配同一把锁，
            # 多副本同时回收时只有第一方能迁移到 failed（ADR-0017）
            row = await session.scalar(select(Run).where(Run.id == rid).with_for_update())
            if row is None or row.status != RunStatus.RUNNING.value:
                return False
            last_event = await session.scalar(
                select(func.max(RunEventRow.created_at)).where(RunEventRow.run_id == rid)
            )
            if (last_event or row.started_at) >= older_than:
                return False
            await append_event_in_session(session, run_id, EventType.RUN_FAILED, payload)
            return True

    async def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_started_at: datetime | None = None,
        before_run_id: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[RunRecord]:
        # 列表也要带事件条数：内存实现一直有值，Postgres 之前恒为 0，
        # 两端不一致会让「清理后 event_count=0」失去参照。按 run 聚合一次即可（≤ limit 行）
        stmt = (
            select(Run, func.count(RunEventRow.seq))
            .outerjoin(RunEventRow, RunEventRow.run_id == Run.id)
            .where(Run.user_id == user_id)
        )
        if status:
            stmt = stmt.where(Run.status == status)
        if session_id is not None:
            stmt = stmt.where(Run.session_id == session_id)
        if before_started_at is not None and before_run_id:
            try:
                before_id = uuid.UUID(before_run_id)
            except ValueError:
                before_id = None
            if before_id is not None:
                stmt = stmt.where(
                    or_(
                        Run.started_at < before_started_at,
                        and_(Run.started_at == before_started_at, Run.id < before_id),
                    )
                )
        stmt = stmt.group_by(Run.id).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [_record_from_row(row, event_count=int(count)) for row, count in rows]

    async def list_sessions(
        self,
        *,
        user_id: str,
        limit: int = 20,
        before_updated_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[SessionSummary]:
        # 标题优先自定义标题（ADR-0040），否则取最早一条非空 input；用窗口函数
        # 按会话取第一行，避免 N+1。搜索同时匹配自定义标题与首条问题：改名后
        # 旧关键词仍然找得到，不会出现「自己刚改的名字搜不到、原来的问题也搜不到」。
        ranked = (
            select(
                Run.session_id,
                Run.input,
                func.row_number()
                .over(
                    partition_by=Run.session_id,
                    order_by=(Run.started_at.asc(), Run.id.asc()),
                )
                .label("rn"),
            )
            .where(
                Run.user_id == user_id,
                func.length(func.regexp_replace(Run.input, r"\s", "", "g")) > 0,
            )
            .subquery()
        )
        first_input = select(ranked.c.session_id, ranked.c.input).where(ranked.c.rn == 1).subquery()
        title = func.coalesce(SessionTitleRow.title, first_input.c.input).label("title")
        agg = (
            select(
                Run.session_id,
                func.min(Run.started_at).label("started_at"),
                func.max(Run.started_at).label("updated_at"),
                func.count().label("run_count"),
                title,
            )
            .where(Run.user_id == user_id)
            .outerjoin(first_input, first_input.c.session_id == Run.session_id)
            .outerjoin(
                SessionTitleRow,
                and_(
                    SessionTitleRow.user_id == Run.user_id,
                    SessionTitleRow.session_id == Run.session_id,
                ),
            )
            # 软移除（ADR-0041）：不算 run 数、不参与排序，也不出现在搜索结果里
            .where(
                ~select(HiddenSessionRow.session_id)
                .where(
                    HiddenSessionRow.user_id == user_id,
                    HiddenSessionRow.session_id == Run.session_id,
                )
                .exists()
            )
            .group_by(Run.session_id, SessionTitleRow.title, first_input.c.input)
        )
        if query:
            # strpos 而不是 LIKE：用户输入里的 % 和 _ 不应变成通配符。
            needle = query.lower()
            agg = agg.where(
                or_(
                    func.strpos(func.lower(func.coalesce(SessionTitleRow.title, "")), needle) > 0,
                    func.strpos(func.lower(func.coalesce(first_input.c.input, "")), needle) > 0,
                )
            )
        if before_updated_at is not None and before_session_id is not None:
            # keyset 作用在聚合结果上：HAVING + max(started_at)/session_id 比较。
            agg = agg.having(
                or_(
                    func.max(Run.started_at) < before_updated_at,
                    and_(
                        func.max(Run.started_at) == before_updated_at,
                        Run.session_id < before_session_id,
                    ),
                )
            )
        agg = agg.order_by(func.max(Run.started_at).desc(), Run.session_id.desc()).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.execute(agg)).all()
        return [
            SessionSummary(
                session_id=row.session_id,
                title=row.title,
                run_count=int(row.run_count),
                started_at=row.started_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def rename_session(self, *, user_id: str, session_id: str, title: str | None) -> bool:
        async with self._sessionmaker() as session:
            exists = await session.scalar(
                select(Run.id).where(Run.user_id == user_id, Run.session_id == session_id).limit(1)
            )
            if exists is None:
                return False
            if title is None:
                await session.execute(
                    delete(SessionTitleRow).where(
                        SessionTitleRow.user_id == user_id,
                        SessionTitleRow.session_id == session_id,
                    )
                )
            else:
                stmt = (
                    pg_insert(SessionTitleRow)
                    .values(
                        user_id=user_id,
                        session_id=session_id,
                        title=title,
                    )
                    .on_conflict_do_update(
                        index_elements=[SessionTitleRow.user_id, SessionTitleRow.session_id],
                        set_={"title": title, "updated_at": func.now()},
                    )
                )
                await session.execute(stmt)
            await session.commit()
        return True

    async def hide_session(self, *, user_id: str, session_id: str) -> bool:
        async with self._sessionmaker() as session:
            has_run = await session.scalar(
                select(Run.id).where(Run.user_id == user_id, Run.session_id == session_id).limit(1)
            )
            if has_run is None:
                return False
            await session.execute(
                pg_insert(HiddenSessionRow)
                .values(user_id=user_id, session_id=session_id)
                .on_conflict_do_nothing(
                    index_elements=[HiddenSessionRow.user_id, HiddenSessionRow.session_id]
                )
            )
            await session.commit()
        return True

    async def list_hidden_sessions(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before_hidden_at: datetime | None = None,
        before_session_id: str | None = None,
        query: str | None = None,
    ) -> list[HiddenSessionSummary]:
        # 标题口径与 list_sessions 一致：自定义标题优先，否则最早一条非空 input。
        # 按 hidden_at 排序而不是最近活动时间——「已移除」视图是运维/找回场景。
        ranked = (
            select(
                Run.session_id,
                Run.input,
                func.row_number()
                .over(
                    partition_by=Run.session_id,
                    order_by=(Run.started_at.asc(), Run.id.asc()),
                )
                .label("rn"),
            )
            .where(
                Run.user_id == user_id,
                func.length(func.regexp_replace(Run.input, r"\s", "", "g")) > 0,
            )
            .subquery()
        )
        first_input = select(ranked.c.session_id, ranked.c.input).where(ranked.c.rn == 1).subquery()
        title = func.coalesce(SessionTitleRow.title, first_input.c.input).label("title")
        stmt = (
            select(
                HiddenSessionRow.session_id,
                HiddenSessionRow.hidden_at,
                title,
                func.count(Run.id).label("run_count"),
            )
            .join(
                Run,
                and_(
                    Run.user_id == HiddenSessionRow.user_id,
                    Run.session_id == HiddenSessionRow.session_id,
                ),
            )
            .outerjoin(first_input, first_input.c.session_id == HiddenSessionRow.session_id)
            .outerjoin(
                SessionTitleRow,
                and_(
                    SessionTitleRow.user_id == HiddenSessionRow.user_id,
                    SessionTitleRow.session_id == HiddenSessionRow.session_id,
                ),
            )
            .where(HiddenSessionRow.user_id == user_id)
        )
        if query:
            # 与主列表同口径：strpos 保证 `%`/`_` 是字面量，同时匹配标题与首条问题
            needle = query.lower()
            stmt = stmt.where(
                or_(
                    func.strpos(func.lower(func.coalesce(SessionTitleRow.title, "")), needle) > 0,
                    func.strpos(func.lower(func.coalesce(first_input.c.input, "")), needle) > 0,
                )
            )
        if before_hidden_at is not None and before_session_id is not None:
            stmt = stmt.where(
                or_(
                    HiddenSessionRow.hidden_at < before_hidden_at,
                    and_(
                        HiddenSessionRow.hidden_at == before_hidden_at,
                        HiddenSessionRow.session_id < before_session_id,
                    ),
                )
            )
        stmt = (
            stmt.group_by(
                HiddenSessionRow.session_id,
                HiddenSessionRow.hidden_at,
                SessionTitleRow.title,
                first_input.c.input,
            )
            .order_by(HiddenSessionRow.hidden_at.desc(), HiddenSessionRow.session_id.desc())
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            HiddenSessionSummary(
                session_id=row.session_id,
                title=row.title,
                run_count=int(row.run_count),
                hidden_at=row.hidden_at,
            )
            for row in rows
        ]

    async def unhide_session(self, *, user_id: str, session_id: str) -> bool:
        return bool(await self.unhide_sessions(user_id=user_id, session_ids=[session_id]))

    async def unhide_sessions(self, *, user_id: str, session_ids: Sequence[str]) -> set[str]:
        unique_ids = list(dict.fromkeys(session_ids))
        if not unique_ids:
            return set()
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                delete(HiddenSessionRow)
                .where(
                    HiddenSessionRow.user_id == user_id,
                    HiddenSessionRow.session_id.in_(unique_ids),
                )
                .returning(HiddenSessionRow.session_id)
            )
            restored = set(result.scalars().all())
            if not restored:
                return set()
            ordered = [session_id for session_id in unique_ids if session_id in restored]
            # 删除与审计同一事务：不能恢复成功而审计丢失；插入失败会回滚删除
            session.add(
                SessionRestoreAuditRow(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    session_ids=ordered,
                    requested_count=len(unique_ids),
                    restored_count=len(ordered),
                    restored_at=datetime.now(UTC),
                )
            )
        return restored

    async def list_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> list[SessionRestoreAuditRecord]:
        stmt = select(SessionRestoreAuditRow)
        if user_id is not None:
            stmt = stmt.where(SessionRestoreAuditRow.user_id == user_id)
        if session_id is not None:
            # JSONB `@>`：数组包含该 session_id；迁移 0020 建了 jsonb_path_ops GIN
            stmt = stmt.where(SessionRestoreAuditRow.session_ids.contains([session_id]))
        if restored_from is not None:
            stmt = stmt.where(SessionRestoreAuditRow.restored_at >= restored_from)
        if restored_to is not None:
            stmt = stmt.where(SessionRestoreAuditRow.restored_at <= restored_to)
        if before is not None:
            before_at, before_id = before
            stmt = stmt.where(
                or_(
                    SessionRestoreAuditRow.restored_at < before_at,
                    and_(
                        SessionRestoreAuditRow.restored_at == before_at,
                        SessionRestoreAuditRow.id < uuid.UUID(before_id),
                    ),
                )
            )
        stmt = stmt.order_by(
            SessionRestoreAuditRow.restored_at.desc(), SessionRestoreAuditRow.id.desc()
        ).limit(limit)
        async with self._sessionmaker() as session:
            rows = (await session.scalars(stmt)).all()
        return [
            SessionRestoreAuditRecord(
                audit_id=str(row.id),
                user_id=row.user_id,
                session_ids=tuple(row.session_ids),
                requested_count=row.requested_count,
                restored_count=row.restored_count,
                restored_at=row.restored_at,
            )
            for row in rows
        ]

    async def count_session_restore_audits(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        restored_from: datetime | None = None,
        restored_to: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(SessionRestoreAuditRow)
        if user_id is not None:
            stmt = stmt.where(SessionRestoreAuditRow.user_id == user_id)
        if session_id is not None:
            stmt = stmt.where(SessionRestoreAuditRow.session_ids.contains([session_id]))
        if restored_from is not None:
            stmt = stmt.where(SessionRestoreAuditRow.restored_at >= restored_from)
        if restored_to is not None:
            stmt = stmt.where(SessionRestoreAuditRow.restored_at <= restored_to)
        async with self._sessionmaker() as session:
            return int((await session.scalar(stmt)) or 0)

    async def session_restore_audit_stats(
        self,
        *,
        since: datetime,
        until: datetime,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionRestoreAuditStats:
        conditions = [
            SessionRestoreAuditRow.restored_at >= since,
            SessionRestoreAuditRow.restored_at <= until,
        ]
        if user_id is not None:
            conditions.append(SessionRestoreAuditRow.user_id == user_id)
        if session_id is not None:
            conditions.append(SessionRestoreAuditRow.session_ids.contains([session_id]))
        summary = (
            select(
                func.count(),
                func.count(func.distinct(SessionRestoreAuditRow.user_id)),
                func.coalesce(func.sum(SessionRestoreAuditRow.restored_count), 0),
            )
            .select_from(SessionRestoreAuditRow)
            .where(*conditions)
        )
        day_column = func.date(func.timezone("UTC", SessionRestoreAuditRow.restored_at))
        daily = (
            select(
                day_column,
                func.count(),
                func.coalesce(func.sum(SessionRestoreAuditRow.restored_count), 0),
            )
            .where(*conditions)
            .group_by(day_column)
            .order_by(day_column)
        )
        async with self._sessionmaker() as session:
            restores, users, sessions = (await session.execute(summary)).one()
            rows = (await session.execute(daily)).all()
        return SessionRestoreAuditStats(
            since=since,
            until=until,
            restores=int(restores),
            users=int(users),
            sessions=int(sessions),
            daily=tuple(
                SessionRestoreAuditDayStats(
                    day=row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0])),
                    restores=int(row[1]),
                    sessions=int(row[2]),
                )
                for row in rows
            ),
        )

    async def prune_session_restore_audits(
        self, *, restored_before: datetime, limit: int = 200, dry_run: bool = False
    ) -> int:
        stmt = (
            select(SessionRestoreAuditRow.id)
            .where(SessionRestoreAuditRow.restored_at < restored_before)
            .order_by(SessionRestoreAuditRow.restored_at)
            .limit(limit)
        )
        async with self._sessionmaker() as session, session.begin():
            ids = (await session.scalars(stmt)).all()
            if dry_run or not ids:
                return len(ids)
            await session.execute(
                delete(SessionRestoreAuditRow).where(SessionRestoreAuditRow.id.in_(ids))
            )
        return len(ids)

    async def list_runs_without_citations(self, *, limit: int = 100) -> list[RunRecord]:
        stmt = (
            select(Run)
            .where(
                # 回填只处理「明确没有引用」的行；JSONB 默认就是 '[]'::jsonb
                func.jsonb_array_length(Run.citations) == 0,
                Run.content_pruned_at.is_(None),
                Run.events_pruned_at.is_(None),
                Run.output.is_not(None),
            )
            .order_by(Run.started_at, Run.id)
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            rows = (await session.scalars(stmt)).all()
        return [_record_from_row(row, event_count=0) for row in rows]

    async def set_citations(self, run_id: str, citations: list[dict[str, Any]]) -> bool:
        rid = uuid.UUID(run_id)
        async with self._sessionmaker() as session, session.begin():
            # 锁行再合并 cited_document_ids：避免与保留清理并发时把快照写回去
            existing = await session.scalar(
                select(Run.cited_document_ids).where(Run.id == rid).with_for_update()
            )
            if existing is None:
                return False
            new_ids = _cited_document_ids(citations) or []
            merged = list(dict.fromkeys([*existing, *new_ids]))
            updated = await session.scalar(
                update(Run)
                .where(
                    Run.id == rid,
                    func.jsonb_array_length(Run.citations) == 0,
                    Run.content_pruned_at.is_(None),
                    Run.events_pruned_at.is_(None),
                    Run.output.is_not(None),
                )
                .values(citations=citations, cited_document_ids=merged)
                .returning(Run.id)
            )
        return updated is not None

    async def recent_turns(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 3,
        exclude_run_id: str | None = None,
    ) -> list[RunTurn]:
        stmt = (
            select(Run.input, Run.output, Run.cited_document_ids)
            .where(
                Run.user_id == user_id,
                Run.session_id == session_id,
                Run.output.is_not(None),
            )
            # 空串/纯空白等价于没有回答（历史数据里可能有 message.completed 的空文本）。
            # 注意 btrim(output) 默认只去空格，不去换行/制表符；这里用 regexp_replace
            # 去掉所有 \s 再判长度，才和内存实现的 .strip() 同口径
            .where(
                func.length(func.regexp_replace(func.coalesce(Run.output, ""), r"\s", "", "g")) > 0
            )
            .order_by(Run.started_at.desc(), Run.id.desc())
            .limit(limit)
        )
        if exclude_run_id:
            try:
                exclude_id: uuid.UUID | None = uuid.UUID(exclude_run_id)
            except ValueError:
                # 非法 id 不可能命中任何一行，忽略即可（不能让历史读取把本轮打挂）
                exclude_id = None
            if exclude_id is not None:
                stmt = stmt.where(Run.id != exclude_id)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            RunTurn(
                query=query,
                answer=answer or "",
                cited_document_ids=tuple(cited or ()),
            )
            for query, answer, cited in reversed(rows)
        ]

    async def prune_events(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedEvents:
        stmt = (
            select(Run.id)
            .where(
                Run.status.in_(tuple(_TERMINAL_STATUSES)),
                Run.events_pruned_at.is_(None),
                Run.finished_at.is_not(None),
                Run.finished_at < finished_before,
            )
            .order_by(Run.finished_at)
            .limit(limit)
        )
        if dry_run:
            async with self._sessionmaker() as session:
                ids = (await session.scalars(stmt)).all()
            return PrunedEvents(run_ids=[str(rid) for rid in ids])

        async with self._sessionmaker() as session, session.begin():
            # SKIP LOCKED：多副本同时清理时各拿各的 run，不会互相等待；
            # 标记写入后下一轮不会再选中同一场 run（删除与标记同事务）
            ids = (await session.scalars(stmt.with_for_update(skip_locked=True))).all()
            if not ids:
                return PrunedEvents(run_ids=[])
            deleted = await session.scalar(
                select(func.count()).select_from(RunEventRow).where(RunEventRow.run_id.in_(ids))
            )
            await session.execute(delete(RunEventRow).where(RunEventRow.run_id.in_(ids)))
            await session.execute(
                update(Run).where(Run.id.in_(ids)).values(events_pruned_at=datetime.now(UTC))
            )
        return PrunedEvents(run_ids=[str(rid) for rid in ids], deleted=int(deleted or 0))

    async def prune_contents(
        self,
        *,
        finished_before: datetime,
        limit: int = 200,
        dry_run: bool = False,
    ) -> PrunedContents:
        stmt = (
            select(Run.id)
            .where(
                Run.status.in_(tuple(_TERMINAL_STATUSES)),
                Run.content_pruned_at.is_(None),
                Run.finished_at.is_not(None),
                Run.finished_at < finished_before,
                # 只选还有正文的 run：手工清过（或迁移前就是空）的 run 不该
                # 每轮都被当成候选，dry-run 也不该把它们列出来
                or_(Run.input != "", Run.output.is_not(None)),
            )
            .order_by(Run.finished_at)
            .limit(limit)
        )
        if dry_run:
            async with self._sessionmaker() as session:
                ids = (await session.scalars(stmt)).all()
            return PrunedContents(run_ids=[str(rid) for rid in ids])

        async with self._sessionmaker() as session, session.begin():
            # SKIP LOCKED：多副本各清各的批次，不互相等待；标记写入后不会再被选中
            ids = (await session.scalars(stmt.with_for_update(skip_locked=True))).all()
            if not ids:
                return PrunedContents(run_ids=[])
            # input 是 NOT NULL 列：置空串而不是 NULL，避免为了删内容改列约束
            await session.execute(
                update(Run)
                .where(Run.id.in_(ids))
                .values(
                    input="",
                    output=None,
                    citations=[],
                    content_pruned_at=datetime.now(UTC),
                )
            )
        return PrunedContents(run_ids=[str(rid) for rid in ids])

    async def find_by_client_msg_id(self, user_id: str, client_msg_id: str) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(Run).where(
                    Run.user_id == user_id,
                    Run.client_msg_id == client_msg_id,
                )
            )
            if row is None:
                return None
            count = await session.scalar(
                select(func.count()).select_from(RunEventRow).where(RunEventRow.run_id == row.id)
            )
        return _record_from_row(row, event_count=int(count or 0))


def _record_from_row(row: Run, *, event_count: int) -> RunRecord:
    return RunRecord(
        run_id=str(row.id),
        user_id=row.user_id,
        session_id=row.session_id,
        input=row.input,
        status=row.status,
        intent=row.intent,
        model=row.model,
        output=row.output,
        step_count=row.step_count,
        max_steps=row.max_steps,
        token_in=row.token_in,
        token_out=row.token_out,
        cost_cents=row.cost_cents,
        error_code=row.error_code,
        failure_category=row.failure_category,
        started_at=row.started_at,
        finished_at=row.finished_at,
        events_pruned_at=row.events_pruned_at,
        content_pruned_at=row.content_pruned_at,
        cited_document_ids=list(row.cited_document_ids or []),
        citations=list(row.citations or []),
        event_count=event_count,
    )


def _event_from_row(row: RunEventRow) -> RunEvent | None:
    try:
        event_type = EventType(row.type)
    except ValueError:
        # 事件类型只增不改（R1）：旧后端读到新事件时忽略而不是 500
        log.warning(
            "unknown_event_type",
            run_id=str(row.run_id),
            seq=row.seq,
            type=row.type,
        )
        return None
    return RunEvent(
        seq=row.seq,
        run_id=str(row.run_id),
        type=event_type,
        ts=row.created_at,
        payload=row.payload or {},
    )


_store: RunStore | None = None


def build_store(settings: Settings) -> RunStore:
    backend = settings.store_backend.strip().lower()
    if backend == "memory":
        return InMemoryRunStore()
    if backend == "postgres":
        from app.core.db import get_sessionmaker

        return PostgresRunStore(get_sessionmaker())
    raise ValueError(f"unknown ONCALL_STORE_BACKEND: {settings.store_backend!r}")


def get_store() -> RunStore:
    """FastAPI 依赖。测试用 `app.dependency_overrides[get_store]` 替换。"""
    global _store
    if _store is None:
        from app.core.config import get_settings

        _store = build_store(get_settings())
    return _store


def set_store(value: RunStore | None) -> None:
    """测试钩子；生产启动时不要调用。"""
    global _store
    _store = value
