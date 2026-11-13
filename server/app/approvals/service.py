"""审批服务：提交、决议、超时回收、审批后恢复运行。

分层约定：
- `api/approvals.py` 只做参数/错误码映射（R4）
- 业务规则（谁是审批人、不能自批、幂等）在这一层
- 存储细节在 `store.py`；runtime 只看到 `ApprovalRecorder` 协议
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.approvals.store import ApprovalStore, OnResolved
from app.approvals.types import (
    ApprovalForbidden,
    ApprovalGroupBy,
    ApprovalNotFound,
    ApprovalNotReady,
    ApprovalRecord,
    ApprovalRequestInfo,
    ApprovalScopeUnsupported,
    ApprovalStats,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.store import RunStore, append_event_in_session
from app.schemas.event import EventType
from app.tools.registry import Identity

log = get_logger(__name__)

DECISIONS = ("approved", "rejected")
SCOPES = ("once", "session")


def _resolved_events(
    record: ApprovalRecord,
    *,
    status: str,
    resolved_by: str,
    reason: str | None,
    scope: str,
) -> list[tuple[EventType, dict[str, Any]]]:
    """决议要落的事件。拒绝/超时必须同时有 run.failed，前端才能确定终态（R1/R2）。"""
    events: list[tuple[EventType, dict[str, Any]]] = [
        (
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": record.id,
                "status": status,
                "resolved_by": resolved_by,
                "reason": reason,
                "scope": scope,
            },
        )
    ]
    if status in ("rejected", "expired"):
        code = "APPROVAL_REJECTED" if status == "rejected" else "APPROVAL_TIMEOUT"
        message = "审批被拒绝，未执行写操作" if status == "rejected" else "审批超时，已转人工处理"
        events.append(
            (EventType.RUN_FAILED, {"error_code": code, "message": message, "at_step": 0})
        )
    return events


class ApprovalService:
    def __init__(
        self,
        store: RunStore,
        approvals: ApprovalStore,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._approvals = approvals
        self._settings = settings or get_settings()

    # ---------- runtime 协议 ----------

    async def request(
        self,
        *,
        run_id: str,
        call_id: str,
        session_id: str | None,
        tool_name: str,
        args: Mapping[str, Any],
        risk_level: str,
        state: Mapping[str, Any],
        requested_by: str,
    ) -> ApprovalRequestInfo:
        """提交审批。同一 run 同一工具已挂起时复用原审批，不生成第二张卡。"""
        existing = await self._approvals.find_pending(run_id=run_id, tool_name=tool_name)
        if existing is not None:
            return ApprovalRequestInfo(existing.id, existing.expires_at)

        now = datetime.now(UTC)
        record = ApprovalRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            call_id=call_id,
            tool_name=tool_name,
            args=dict(args),
            risk_level=risk_level,
            status="pending",
            requested_by=requested_by,
            expires_at=now + timedelta(minutes=self._settings.approval_ttl_min),
            created_at=now,
            session_id=session_id,
            state=dict(state),
        )
        try:
            await self._approvals.create(record)
        except IntegrityError:
            # 并发：部分唯一索引兜底，回读已存在的待办
            existing = await self._approvals.find_pending(run_id=run_id, tool_name=tool_name)
            if existing is None:
                raise
            return ApprovalRequestInfo(existing.id, existing.expires_at)
        return ApprovalRequestInfo(record.id, record.expires_at)

    async def is_granted(self, *, user_id: str, session_id: str | None, tool_name: str) -> bool:
        if not session_id:
            return False
        return await self._approvals.is_granted(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            at=datetime.now(UTC),
        )

    # ---------- 查询 ----------

    async def expire_due(self) -> list[ApprovalRecord]:
        """把已超时的待办置 expired，并把 run 推到 failed(APPROVAL_TIMEOUT)。"""
        now = datetime.now(UTC)
        pending = await self._approvals.list(status="pending", limit=200)
        expired: list[ApprovalRecord] = []
        for record in pending:
            if record.expires_at > now:
                continue
            reason = "审批超时，已转人工"
            events = _resolved_events(
                record, status="expired", resolved_by="system", reason=reason, scope="once"
            )
            updated, changed = await self._approvals.resolve(
                record.id,
                status="expired",
                resolved_by="system",
                reason=reason,
                scope="once",
                at=now,
                on_resolved=self._event_writer(record.run_id, events),
            )
            if changed and updated is not None:
                expired.append(updated)
        return expired

    async def list_for(
        self,
        identity: Identity,
        *,
        status: str = "pending",
        limit: int = 100,
        before: tuple[datetime, datetime, str] | None = None,
    ) -> list[ApprovalRecord]:
        await self.expire_due()
        approver = self._is_approver(identity)
        # 审批人看全部待办；普通员工只看自己发起的
        requested_by = None if approver else identity.user_id
        before_expires_at, before_created_at, before_id = before or (None, None, None)
        return await self._approvals.list(
            status=status,
            requested_by=requested_by,
            before_expires_at=before_expires_at,
            before_created_at=before_created_at,
            before_id=before_id,
            limit=limit,
        )

    async def stats(
        self,
        identity: Identity,
        *,
        days: int,
        now: datetime | None = None,
        group_by: ApprovalGroupBy | None = None,
    ) -> ApprovalStats:
        """审批人视角的积压与等待统计（ADR-0048）。

        先收敛已过期的待办：统计口径是「还未过期、仍值得处理的积压」，不把
        TTL 已过但尚未落状态的单算成「卡住」。收敛会改状态，所以时刻取在收敛
        之后，年龄与窗口边界都以返回时的状态为准。等待时长只统计窗口内
        approved/rejected，不含 expired。
        """
        if not self._is_approver(identity):
            raise ApprovalForbidden("需要审批人角色")
        await self.expire_due()
        at = now or datetime.now(UTC)
        return await self._approvals.stats(
            since=at - timedelta(days=days), now=at, group_by=group_by
        )

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        return await self._approvals.get(approval_id)

    # ---------- 决议 ----------

    async def resolve(
        self,
        approval_id: str,
        identity: Identity,
        *,
        decision: str,
        reason: str | None = None,
        scope: str = "once",
    ) -> ApprovalRecord:
        if decision not in DECISIONS:
            raise ApprovalScopeUnsupported(f"未知审批结论: {decision}")
        if scope not in SCOPES:
            raise ApprovalScopeUnsupported(f"未知授权范围: {scope}")

        record = await self._approvals.get(approval_id)
        if record is None:
            raise ApprovalNotFound(approval_id)
        if not self._is_approver(identity):
            raise ApprovalForbidden("需要审批人角色")
        if identity.user_id == record.requested_by:
            raise ApprovalForbidden("不能审批自己发起的操作")

        if record.is_pending:
            # 防止「审批人比 approval.required 先到」的竞态：此时序列会变成
            # resolved(N) → required(N+1)，run 永远停在 awaiting_approval
            run_status = await self._store.status(record.run_id)
            if run_status != "awaiting_approval":
                raise ApprovalNotReady("run 尚未进入待审批状态，请稍后重试")

        now = datetime.now(UTC)
        if record.is_pending and record.expires_at <= now:
            reason = "审批超时，已转人工"
            expired_events = _resolved_events(
                record, status="expired", resolved_by="system", reason=reason, scope="once"
            )
            updated, _ = await self._approvals.resolve(
                approval_id,
                status="expired",
                resolved_by="system",
                reason=reason,
                scope="once",
                at=now,
                on_resolved=self._event_writer(record.run_id, expired_events),
            )
            return updated or record

        grant_until = (
            now + timedelta(hours=self._settings.approval_grant_hours)
            if decision == "approved" and scope == "session"
            else None
        )
        events = _resolved_events(
            record,
            status=decision,
            resolved_by=identity.user_id,
            reason=reason,
            scope=scope,
        )
        updated, changed = await self._approvals.resolve(
            approval_id,
            status=decision,
            resolved_by=identity.user_id,
            reason=reason,
            scope=scope,
            at=now,
            grant_until=grant_until,
            on_resolved=self._event_writer(record.run_id, events),
        )
        if updated is None:
            raise ApprovalNotFound(approval_id)
        if not changed:
            # 幂等：重复 resolve 返回首次结果，不重复执行工具（docs/06 §7）
            return updated

        if decision == "approved":
            await self._resume(updated)
        return await self._approvals.get(approval_id) or updated

    # ---------- 内部 ----------

    def _is_approver(self, identity: Identity) -> bool:
        return bool(set(self._settings.approver_role_list).intersection(identity.roles))

    def _event_writer(
        self, run_id: str, events: list[tuple[EventType, dict[str, Any]]]
    ) -> OnResolved:
        """把决议事件写进存储层给的同一个事务；内存实现传 None，退回逐条 append。"""

        async def write(session: Any) -> None:
            for event_type, payload in events:
                if session is not None:
                    await append_event_in_session(session, run_id, event_type, payload)
                else:
                    await self._store.append(run_id, event_type, payload)

        return write

    async def _resume(self, record: ApprovalRecord) -> None:
        # 延迟导入：runtime 依赖 ApprovalRecorder 协议，这里不能形成循环导入
        from app.agent.runtime import build_deps
        from app.agent.runtime import resume as runtime_resume

        run = await self._store.get(record.run_id)
        max_steps = run.max_steps if run is not None else 12
        try:
            async for event_type, payload in runtime_resume(
                approval=record,
                deps=build_deps(approvals=self),
                max_steps=max_steps,
            ):
                await self._store.append(record.run_id, event_type, payload)
        except Exception:
            log.exception(
                "approval_resume_failed",
                run_id=record.run_id,
                approval_id=record.id,
            )
            await self._store.append(
                record.run_id,
                EventType.RUN_FAILED,
                {
                    "error_code": "INTERNAL_ERROR",
                    "message": "审批后恢复执行失败",
                    "at_step": 0,
                },
            )


def approval_payload(record: ApprovalRecord) -> dict[str, Any]:
    """API 输出。args/state 里的 state 不返回给前端（内部快照）。"""
    return {
        "approval_id": record.id,
        "run_id": record.run_id,
        "call_id": record.call_id,
        "tool": record.tool_name,
        "args": record.args,
        "risk_level": record.risk_level,
        "status": record.status,
        "requested_by": record.requested_by,
        "resolved_by": record.resolved_by,
        "reason": record.reason,
        "scope": record.scope,
        "expires_at": record.expires_at,
        "created_at": record.created_at,
        "resolved_at": record.resolved_at,
    }
