"""工具注册、试调用与权限矩阵（W5 D22/D23）。

三个原则：

- 工具定义仍在代码里，接口只暴露「读」；管理页能改的是本环境的启用/角色覆盖
- 试调用**必须**走 `ToolGuard`，写工具只返回 `requires_approval`，不会真的落单
- 矩阵提交是整份覆盖的替换，但只更新请求里列出的工具；没列出的保持原样
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.api.export_audits import MAX_EXPORT_ROWS, record_export
from app.core.config import get_settings
from app.core.csv import csv_document
from app.core.logging import get_logger
from app.core.roles import role_catalog
from app.core.store import RunStore, get_store
from app.schemas.tool import (
    PermMatrixResponse,
    PermMatrixTool,
    PermMatrixUpdateRequest,
    PermMatrixUpdateResponse,
    ToolChangeOut,
    ToolHistoryResponse,
    ToolListResponse,
    ToolOut,
    ToolOverrideSnapshot,
    ToolTestRequest,
    ToolTestResponse,
    ToolUpdateRequest,
)
from app.tools.builtin import default_registry
from app.tools.policy import (
    ToolOverride,
    ToolPolicy,
    ToolSettingChange,
    ToolSettingChangeRecord,
    get_tool_policy,
    override_snapshot,
)
from app.tools.registry import Identity, ToolGuard, ToolSpec

router = APIRouter(prefix="/admin", tags=["admin-tools"])
log = get_logger(__name__)

#: 历史保留期与事件/审计一致，最多查询 365 天的闭区间。
MAX_HISTORY_RANGE_DAYS = 365


def _history_window(
    changed_from: date | None, changed_to: date | None
) -> tuple[datetime | None, datetime | None]:
    """把 UTC 自然日闭区间换算成左闭右开时间窗口（ADR-0098）。"""
    if (changed_from is None) != (changed_to is None):
        raise ApiError(422, "INVALID_RANGE", "changed_from 与 changed_to 必须同时提供")
    if changed_from is None:
        return None, None
    assert changed_to is not None
    if changed_to < changed_from:
        raise ApiError(422, "INVALID_RANGE", "changed_from 不能晚于 changed_to")
    if (changed_to - changed_from).days + 1 > MAX_HISTORY_RANGE_DAYS:
        raise ApiError(422, "INVALID_RANGE", "日期范围不能超过 365 天")
    if changed_to == date.max:
        # 右开上界需要 changed_to + 1 天；date.max 无法再往后一天，直接拒绝而不是 500。
        raise ApiError(422, "INVALID_RANGE", "changed_to 超出支持范围")
    since = datetime.combine(changed_from, time.min, tzinfo=UTC)
    until = datetime.combine(changed_to + timedelta(days=1), time.min, tzinfo=UTC)
    return since, until


#: 工具历史游标：绑定工具名与已应用筛选，换筛选后旧游标必须 400；
#: 有效期默认 1 小时（ADR-0102），可由 ONCALL_TOOL_HISTORY_CURSOR_TTL_MINUTES 调整（ADR-0105）。
TOOL_HISTORY_CURSOR_MAX = 512
TOOL_HISTORY_CURSOR_TTL_S = 60 * 60


def _history_fingerprint(
    name: str,
    since: datetime | None,
    until: datetime | None,
    changed_by: str | None,
    source: str | None,
    order: str,
) -> str:
    # 只存指纹，不把工具名/过滤原值塞进游标；与非 ASCII 值解耦。
    raw = "\0".join(
        (
            name,
            since.isoformat() if since else "",
            until.isoformat() if until else "",
            changed_by or "",
            source or "",
            order,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _encode_tool_history_cursor(
    record: ToolSettingChangeRecord,
    fingerprint: str,
    *,
    now: datetime | None = None,
    ttl_s: int = TOOL_HISTORY_CURSOR_TTL_S,
) -> str:
    issued_at = now or datetime.now(UTC)
    raw = json.dumps(
        {
            "t": record.changed_at.isoformat(),
            "i": record.id,
            "f": fingerprint,
            "e": int(issued_at.timestamp()) + ttl_s,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_tool_history_cursor(
    cursor: str,
    fingerprint: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, int]:
    if len(cursor) > TOOL_HISTORY_CURSOR_MAX:
        raise ApiError(400, "INVALID_CURSOR", "游标无效或已过期")
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        changed_at = datetime.fromisoformat(payload["t"])
        audit_id = int(payload["i"])
        cursor_fingerprint = payload["f"]
        expires_at = payload["e"]
        if type(expires_at) is not int:
            raise ValueError("cursor expiry must be an integer")
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError, binascii.Error) as exc:
        raise ApiError(400, "INVALID_CURSOR", "游标无效或已过期") from exc
    if changed_at.tzinfo is None or cursor_fingerprint != fingerprint or audit_id < 1:
        raise ApiError(400, "INVALID_CURSOR", "游标无效或已过期")
    current_timestamp = int((now or datetime.now(UTC)).timestamp())
    if expires_at < current_timestamp:
        raise ApiError(400, "CURSOR_EXPIRED", "游标已过期，请重新加载")
    return changed_at, audit_id


TOOL_HISTORY_CSV_HEADERS = (
    "tool_name",
    "changed_at",
    "changed_by",
    "source",
    "before",
    "after",
)


def _tool_history_csv(records: Sequence[ToolSettingChangeRecord]) -> str:
    return csv_document(
        TOOL_HISTORY_CSV_HEADERS,
        (
            (
                record.tool_name,
                record.changed_at,
                record.changed_by,
                record.source,
                ""
                if record.before is None
                else json.dumps(record.before, ensure_ascii=False, sort_keys=True),
                ""
                if record.after is None
                else json.dumps(record.after, ensure_ascii=False, sort_keys=True),
            )
            for record in records
        ),
    )


def _safe_filename_part(value: str) -> str:
    """避免工具名中的引号/路径字符进入 Content-Disposition。"""
    return (
        "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "-_" else "_" for ch in value)[:64]
        or "tool"
    )


def _tool_out(
    spec: ToolSpec,
    effective: ToolSpec,
    *,
    overridden: bool,
) -> ToolOut:
    return ToolOut(
        name=spec.name,
        description=spec.description,
        input_schema=dict(spec.input_schema),
        is_write=spec.is_write,
        timeout_ms=spec.timeout_ms,
        roles=list(effective.roles),
        enabled=effective.enabled,
        code_enabled=spec.enabled,
        overridden=overridden,
    )


async def _matrix(policy: ToolPolicy, *, allow_stale: bool = True) -> PermMatrixResponse:
    overrides = await policy.overrides(force=True, allow_stale=allow_stale)
    tools: list[PermMatrixTool] = []
    for spec in default_registry().all():
        override = overrides.get(spec.name)
        effective = policy.effective_spec(spec, override)
        tools.append(
            PermMatrixTool(
                name=spec.name,
                description=spec.description,
                is_write=spec.is_write,
                enabled=effective.enabled,
                code_enabled=spec.enabled,
                default_roles=list(spec.roles),
                default_enabled=spec.enabled,
                roles=list(effective.roles),
                overridden=override is not None,
            )
        )
    return PermMatrixResponse(roles=role_catalog(get_settings()), tools=tools)


@router.get("/tools")
async def list_tools(
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    _admin: Annotated[Identity, Depends(require_admin)],
) -> ToolListResponse:
    try:
        # 管理页展示的必须是真实配置，不能拿旧快照冒充当前状态
        overrides = await policy.overrides(allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("tool_settings_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具配置暂不可用") from exc
    items: list[ToolOut] = []
    for spec in default_registry().all():
        override = overrides.get(spec.name)
        items.append(
            _tool_out(
                spec,
                policy.effective_spec(spec, override),
                overridden=override is not None,
            )
        )
    return ToolListResponse(items=items)


@router.patch("/tools/{name}")
async def update_tool(
    name: str,
    body: ToolUpdateRequest,
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> ToolOut:
    spec = default_registry().try_get(name)
    if spec is None:
        raise ApiError(404, "TOOL_NOT_FOUND", "工具未注册")

    if "enabled" not in body.model_fields_set:
        override = await policy.override_for(name)
        return _tool_out(
            spec,
            policy.effective_spec(spec, override),
            overridden=override is not None,
        )

    if body.enabled is True and not spec.enabled:
        raise ApiError(422, "TOOL_LOCKED", "该工具在代码中已禁用，管理页不能开启")

    try:
        current = (await policy.overrides(force=True, allow_stale=False)).get(name)
        if body.enabled is None or body.enabled == spec.enabled:
            # 撤销启用覆盖；若角色还有覆盖则保留 roles
            if current is None or current.roles is None:
                new_override = None
            else:
                new_override = ToolOverride(enabled=None, roles=current.roles)
        else:
            new_override = ToolOverride(
                enabled=body.enabled,
                roles=current.roles if current is not None else None,
            )
        before = override_snapshot(current)
        after = override_snapshot(new_override)
        change = None
        if before != after:
            change = ToolSettingChange(
                tool_name=name,
                changed_by=admin.user_id,
                source="tool",
                before=before,
                after=after,
            )
        await policy.set_override(name, new_override, updated_by=admin.user_id, change=change)
    except SQLAlchemyError as exc:
        log.error("tool_setting_write_failed", tool=name, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具配置保存失败，请稍后重试") from exc

    override = await policy.override_for(name)
    log.info("tool_setting_updated", tool=name, enabled=body.enabled, by=admin.user_id)
    return _tool_out(
        spec,
        policy.effective_spec(spec, override),
        overridden=override is not None,
    )


@router.get("/tools/{name}/history")
async def tool_setting_history(
    name: Annotated[str, Path(min_length=1, max_length=64)],
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    _admin: Annotated[Identity, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    changed_from: Annotated[date | None, Query()] = None,
    changed_to: Annotated[date | None, Query()] = None,
    changed_by: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    source: Annotated[str | None, Query(pattern="^(tool|matrix|rollback)$")] = None,
    order: Annotated[Literal["latest", "earliest"], Query()] = "latest",
    # 长度交给 _decode 统一判 400；Query max_length 会让超长游标变成 422。
    cursor: Annotated[str | None, Query()] = None,
) -> ToolHistoryResponse:
    # 不要求工具仍在注册表里：工具下线/改名后，历史仍要能按旧名字查到，
    # 否则「长期审计」在工具下线那一刻就断了。从未注册过的名字只会得到空列表。
    since, until = _history_window(changed_from, changed_to)
    fingerprint = _history_fingerprint(name, since, until, changed_by, source, order)
    cursor_key = _decode_tool_history_cursor(cursor, fingerprint) if cursor is not None else None
    total: int | None = None
    try:
        if cursor_key is None:
            total = await policy.count_history(
                name,
                since=since,
                until=until,
                changed_by=changed_by,
                source=source,
            )
        records = await policy.history(
            name,
            limit=limit,
            since=since,
            until=until,
            changed_by=changed_by,
            source=source,
            before=cursor_key if order == "latest" else None,
            after=cursor_key if order == "earliest" else None,
            order="desc" if order == "latest" else "asc",
        )
    except SQLAlchemyError as exc:
        log.error("tool_history_read_failed", tool=name, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具变更历史暂不可用") from exc
    # 计数和列表非同一快照；列表比计数多时不能给出矛盾的总数。
    if total is not None and total < len(records):
        total = None
    has_more = len(records) == limit and (total is None or total > len(records))
    return ToolHistoryResponse(
        items=[
            ToolChangeOut(
                id=record.id,
                tool_name=record.tool_name,
                changed_by=record.changed_by,
                changed_at=record.changed_at,
                source=record.source,
                before=None if record.before is None else ToolOverrideSnapshot(**record.before),
                after=None if record.after is None else ToolOverrideSnapshot(**record.after),
            )
            for record in records
        ],
        total=total,
        next_cursor=(
            _encode_tool_history_cursor(
                records[-1],
                fingerprint,
                ttl_s=get_settings().tool_history_cursor_ttl_s,
            )
            if has_more and records
            else None
        ),
    )


def _override_from_snapshot(snapshot: ToolOverrideSnapshot | None) -> ToolOverride | None:
    """把历史快照还原成覆盖；None 表示删除覆盖、回到代码默认。"""
    if snapshot is None:
        return None
    roles = None if snapshot.roles is None else tuple(snapshot.roles)
    return ToolOverride(enabled=snapshot.enabled, roles=roles)


@router.post("/tools/{name}/history/{change_id}/rollback")
async def rollback_tool_setting(
    name: Annotated[str, Path(min_length=1, max_length=64)],
    change_id: Annotated[int, Path(ge=1)],
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> ToolOut:
    """把工具配置回滚到某条变更发生前的状态（ADR-0112）。"""
    spec = default_registry().try_get(name)
    if spec is None:
        raise ApiError(404, "TOOL_NOT_FOUND", "工具未注册")
    try:
        record = await policy.get_history(name, change_id)
        if record is None:
            raise ApiError(404, "HISTORY_NOT_FOUND", "变更记录不存在")
        target = _override_from_snapshot(
            None if record.before is None else ToolOverrideSnapshot(**record.before)
        )
        if target is not None and target.enabled is True and not spec.enabled:
            raise ApiError(422, "TOOL_LOCKED", "该工具在代码中已禁用，不能通过回滚开启")
        current = (await policy.overrides(force=True, allow_stale=False)).get(name)
        if current != target:
            change = ToolSettingChange(
                tool_name=name,
                changed_by=admin.user_id,
                source="rollback",
                before=override_snapshot(current),
                after=override_snapshot(target),
            )
            await policy.set_override(name, target, updated_by=admin.user_id, change=change)
        override = await policy.override_for(name)
    except SQLAlchemyError as exc:
        log.error("tool_setting_rollback_failed", tool=name, change_id=change_id, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具配置回滚失败，请稍后重试") from exc
    log.info(
        "tool_setting_rolled_back",
        tool=name,
        change_id=change_id,
        by=admin.user_id,
    )
    return _tool_out(
        spec,
        policy.effective_spec(spec, override),
        overridden=override is not None,
    )


@router.get("/tools/{name}/history/export")
async def export_tool_history(
    name: Annotated[str, Path(min_length=1, max_length=64)],
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    store: Annotated[RunStore, Depends(get_store)],
    admin: Annotated[Identity, Depends(require_admin)],
    changed_from: Annotated[date | None, Query()] = None,
    changed_to: Annotated[date | None, Query()] = None,
    changed_by: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    source: Annotated[str | None, Query(pattern="^(tool|matrix|rollback)$")] = None,
    order: Annotated[Literal["latest", "earliest"], Query()] = "latest",
) -> Response:
    """导出工具配置变更历史 CSV；导出自身写下载审计（ADR-0099）。"""
    since, until = _history_window(changed_from, changed_to)
    try:
        records = await policy.history(
            name,
            limit=MAX_EXPORT_ROWS + 1,
            since=since,
            until=until,
            changed_by=changed_by,
            source=source,
            order="desc" if order == "latest" else "asc",
        )
    except SQLAlchemyError as exc:
        log.error("tool_history_export_failed", tool=name, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具变更历史暂不可用") from exc
    truncated = len(records) > MAX_EXPORT_ROWS
    rows = records[:MAX_EXPORT_ROWS]
    content = _tool_history_csv(rows)
    await record_export(
        store,
        user_id=admin.user_id,
        resource="tool_setting_history",
        filters={
            "tool": name,
            "changed_from": changed_from.isoformat() if changed_from else None,
            "changed_to": changed_to.isoformat() if changed_to else None,
            "changed_by": changed_by,
            "source": source,
            **({"order": order} if order != "latest" else {}),
        },
        row_count=len(rows),
        truncated=truncated,
        content=content,
    )
    filename = f"tool-history-{_safe_filename_part(name)}-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Export-Count": str(len(rows)),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


@router.post("/tools/{name}/test")
async def test_tool(
    name: str,
    body: ToolTestRequest,
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    identity: Annotated[Identity, Depends(require_admin)],
) -> ToolTestResponse:
    spec = default_registry().try_get(name)
    if spec is None:
        raise ApiError(404, "TOOL_NOT_FOUND", "工具未注册")

    guard = ToolGuard(default_registry(), policy=policy)
    result = await guard.execute(
        name,
        body.args,
        identity,
        call_id=f"test_{uuid.uuid4().hex[:10]}",
        # 写操作只验证「会挂起审批」，不能借管理页试调用真的执行
        allow_write=False,
    )
    log.info(
        "tool_tested",
        tool=name,
        by=identity.user_id,
        decision=result.decision.value,
        status=result.status.value,
        duration_ms=result.duration_ms,
    )
    return ToolTestResponse(
        tool=name,
        decision=result.decision.value,
        status=result.status.value,
        result=result.result,
        error=result.error,
        error_kind=result.error_kind,
        duration_ms=result.duration_ms,
        attempts=result.attempts,
    )


@router.get("/perm-matrix")
async def get_perm_matrix(
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    _admin: Annotated[Identity, Depends(require_admin)],
) -> PermMatrixResponse:
    try:
        return await _matrix(policy, allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("perm_matrix_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "权限矩阵暂不可用") from exc


@router.put("/perm-matrix")
async def update_perm_matrix(
    body: PermMatrixUpdateRequest,
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    admin: Annotated[Identity, Depends(require_admin)],
) -> PermMatrixUpdateResponse:
    registry = default_registry()
    catalog = set(role_catalog(get_settings()))
    try:
        # 读失败时不能把空快照当真：随后的 replace 会静默删掉所有覆盖
        loaded = await policy.overrides(force=True, allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("perm_matrix_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "权限矩阵暂不可用") from exc
    current = {
        name: override for name, override in loaded.items() if registry.try_get(name) is not None
    }
    seen: set[str] = set()
    for item in body.tools:
        spec = registry.try_get(item.name)
        if spec is None:
            raise ApiError(422, "INVALID_ARGS", f"工具未注册: {item.name}")
        if item.name in seen:
            raise ApiError(422, "INVALID_ARGS", f"工具重复提交: {item.name}")
        seen.add(item.name)
        if item.enabled and not spec.enabled:
            raise ApiError(422, "TOOL_LOCKED", f"工具在代码中已禁用: {item.name}")
        roles = tuple(dict.fromkeys(item.roles))
        unknown = sorted(set(roles) - catalog)
        if unknown:
            raise ApiError(422, "INVALID_ARGS", f"未知角色: {', '.join(unknown)}")

        enabled = None if item.enabled == spec.enabled else item.enabled
        role_override = None if roles == spec.roles else roles
        if enabled is None and role_override is None:
            current.pop(item.name, None)
        else:
            current[item.name] = ToolOverride(enabled=enabled, roles=role_override)

    # 只记录真正变化的工具；整表保存但内容没变时不产生审计噪声
    before_snapshots = {name: override_snapshot(item) for name, item in loaded.items()}
    after_snapshots = {name: override_snapshot(item) for name, item in current.items()}
    changes = [
        ToolSettingChange(
            tool_name=name,
            changed_by=admin.user_id,
            source="matrix",
            before=before_snapshots.get(name),
            after=after_snapshots.get(name),
        )
        for name in sorted(before_snapshots.keys() | after_snapshots.keys())
        if before_snapshots.get(name) != after_snapshots.get(name)
    ]
    try:
        await policy.replace_overrides(current, updated_by=admin.user_id, changes=changes)
    except SQLAlchemyError as exc:
        log.error("perm_matrix_write_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "权限矩阵保存失败，请稍后重试") from exc

    log.info("perm_matrix_updated", tools=len(seen), changes=len(changes), by=admin.user_id)
    try:
        matrix = await _matrix(policy, allow_stale=False)
    except SQLAlchemyError as exc:
        log.error("perm_matrix_read_failed", error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "权限矩阵已保存，但回读失败") from exc
    return PermMatrixUpdateResponse(roles=matrix.roles, tools=matrix.tools)
