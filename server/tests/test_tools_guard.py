"""工具治理的回归测试 —— 这些用例就是"越权拦截 100%"的证据。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.tools import (
    Decision,
    Identity,
    ToolError,
    ToolErrorKind,
    ToolGuard,
    ToolRegistry,
    ToolSpec,
    ToolStatus,
)

EMPLOYEE = Identity(user_id="u_102", roles=frozenset({"employee"}))
IT_SUPPORT = Identity(user_id="u_201", roles=frozenset({"it_support"}))


async def _echo(**kwargs: Any) -> dict[str, Any]:
    return {"echo": kwargs}


async def _slow(**kwargs: Any) -> dict[str, Any]:
    await asyncio.sleep(0.2)
    return {"ok": True}


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="query_cmdb",
            description="按负责人查资产",
            input_schema={
                "type": "object",
                "properties": {"owner_id": {"type": "string"}},
                "required": ["owner_id"],
            },
            handler=_echo,
            timeout_ms=500,
        )
    )
    reg.register(
        ToolSpec(
            name="run_diagnostic",
            description="只读检测，仅 IT 支持可用",
            input_schema={"type": "object", "properties": {}},
            handler=_echo,
            roles=("it_support",),
            timeout_ms=500,
        )
    )
    reg.register(
        ToolSpec(
            name="create_ticket",
            description="创建工单（写操作）",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
            handler=_echo,
            is_write=True,
            timeout_ms=500,
        )
    )
    reg.register(
        ToolSpec(
            name="flaky_tool",
            description="永远超时",
            input_schema={"type": "object", "properties": {}},
            handler=_slow,
            timeout_ms=10,
            max_attempts=2,
        )
    )
    return reg


def _guard() -> ToolGuard:
    return ToolGuard(_registry(), backoff_base_ms=1)


async def test_unknown_tool_denied() -> None:
    res = await _guard().execute("rm_rf", {}, EMPLOYEE, call_id="c1")
    assert res.decision is Decision.DENIED
    assert res.error_kind == ToolErrorKind.NOT_FOUND.value


async def test_reserved_identity_arg_denied() -> None:
    res = await _guard().execute(
        "query_cmdb", {"owner_id": "u_102", "user_id": "admin"}, EMPLOYEE, call_id="c2"
    )
    assert res.decision is Decision.DENIED
    assert "user_id" in (res.error or "")


async def test_role_check() -> None:
    denied = await _guard().execute("run_diagnostic", {}, EMPLOYEE, call_id="c3")
    assert denied.decision is Decision.DENIED

    allowed = await _guard().execute("run_diagnostic", {}, IT_SUPPORT, call_id="c4")
    assert allowed.status is ToolStatus.OK


async def test_write_tool_requires_approval_and_does_not_execute() -> None:
    res = await _guard().execute("create_ticket", {"title": "打印机离线"}, EMPLOYEE, call_id="c5")
    assert res.decision is Decision.REQUIRES_APPROVAL
    assert res.result is None
    assert res.approval is not None
    assert res.approval["tool"] == "create_ticket"


async def test_write_tool_runs_after_approval() -> None:
    res = await _guard().execute(
        "create_ticket", {"title": "打印机离线"}, EMPLOYEE, call_id="c6", allow_write=True
    )
    assert res.status is ToolStatus.OK


async def test_missing_required_arg() -> None:
    res = await _guard().execute("query_cmdb", {}, EMPLOYEE, call_id="c7")
    assert res.status is ToolStatus.ERROR
    assert res.error_kind == ToolErrorKind.INVALID_ARGS.value


async def test_timeout_is_retried_then_reported() -> None:
    res = await _guard().execute("flaky_tool", {}, EMPLOYEE, call_id="c8")
    assert res.status is ToolStatus.TIMEOUT
    assert res.attempts == 2  # max_attempts=2，不会无限重试


async def test_non_retryable_error_is_not_retried() -> None:
    async def boom(**kwargs: Any) -> dict[str, Any]:
        raise ToolError(ToolErrorKind.INVALID_ARGS, "参数非法")

    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="boom",
            description="永远参数错",
            input_schema={"type": "object", "properties": {}},
            handler=boom,
        )
    )
    res = await ToolGuard(reg, backoff_base_ms=1).execute("boom", {}, EMPLOYEE, call_id="c9")
    assert res.status is ToolStatus.ERROR
    assert res.attempts == 1


@pytest.mark.parametrize("bad", ["user_id", "ROLE", "Tenant_ID", "permissions"])
async def test_reserved_args_case_insensitive(bad: str) -> None:
    res = await _guard().execute("query_cmdb", {"owner_id": "u", bad: "x"}, EMPLOYEE, call_id="c10")
    assert res.decision is Decision.DENIED
