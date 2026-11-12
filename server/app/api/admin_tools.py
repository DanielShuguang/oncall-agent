"""工具注册、试调用与权限矩阵（W5 D22/D23）。

三个原则：

- 工具定义仍在代码里，接口只暴露「读」；管理页能改的是本环境的启用/角色覆盖
- 试调用**必须**走 `ToolGuard`，写工具只返回 `requires_approval`，不会真的落单
- 矩阵提交是整份覆盖的替换，但只更新请求里列出的工具；没列出的保持原样
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.roles import role_catalog
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
    get_tool_policy,
    override_snapshot,
)
from app.tools.registry import Identity, ToolGuard, ToolSpec

router = APIRouter(prefix="/admin", tags=["admin-tools"])
log = get_logger(__name__)


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
    name: str,
    policy: Annotated[ToolPolicy, Depends(get_tool_policy)],
    _admin: Annotated[Identity, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ToolHistoryResponse:
    if default_registry().try_get(name) is None:
        raise ApiError(404, "TOOL_NOT_FOUND", "工具未注册")
    try:
        records = await policy.history(name, limit=limit)
    except SQLAlchemyError as exc:
        log.error("tool_history_read_failed", tool=name, error=str(exc))
        raise ApiError(503, "DATABASE_UNAVAILABLE", "工具变更历史暂不可用") from exc
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
        ]
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
