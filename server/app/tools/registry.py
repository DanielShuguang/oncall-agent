"""工具注册与治理 —— 全项目最核心的模块。

设计见 docs/06-tool-governance.md。核心原则：

    模型负责产出意图和参数，判断和执行必须在业务代码里。

五道闸门（顺序不可换）：
    ① 存在性  ② 保留字段  ③ 权限  ④ 白名单/启用  ⑤ 写操作 → 审批
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

Handler = Callable[..., Awaitable[Any]]

#: 身份类字段只能由服务端会话注入，模型给的这类参数一律拒绝。
RESERVED_ARGS: frozenset[str] = frozenset(
    {
        "user_id",
        "userid",
        "user",
        "role",
        "roles",
        "permission",
        "permissions",
        "tenant",
        "tenant_id",
        "is_admin",
        # 执行期由 ToolGuard 注入；模型传这些字段等于伪造身份
        "identity",
        "requester",
        "requested_by",
        "resolved_by",
        "approver",
        "session_id",
    }
)


class ToolErrorKind(StrEnum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    INVALID_ARGS = "invalid_args"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    INTERNAL = "internal"


class ToolError(Exception):
    def __init__(
        self,
        kind: ToolErrorKind,
        message: str,
        *,
        idempotent_safe: bool = False,
    ) -> None:
        super().__init__(f"{kind.value}: {message}")
        self.kind = kind
        self.message = message
        #: 该错误发生后重试是否安全（写操作必须显式声明）
        self.idempotent_safe = idempotent_safe


class Decision(StrEnum):
    EXECUTED = "executed"
    REQUIRES_APPROVAL = "requires_approval"
    DENIED = "denied"


class ToolStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass(frozen=True, slots=True)
class Identity:
    """调用者身份。只能来自服务端会话，绝不能来自模型输出。"""

    user_id: str
    roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Handler
    is_write: bool = False
    timeout_ms: int = 3000
    roles: tuple[str, ...] = ()
    retryable: tuple[str, ...] = ("timeout", "network", "rate_limited")
    max_attempts: int = 3
    enabled: bool = True
    #: handler 需要服务端身份（如 create_ticket 的 requester）；由 ToolGuard 注入，
    #: 不经过 args，模型无法伪造（R9）
    inject_identity: bool = False


@dataclass(slots=True)
class ToolCallResult:
    call_id: str
    tool: str
    decision: Decision
    status: ToolStatus
    result: Any = None
    error_kind: str | None = None
    error: str | None = None
    duration_ms: int = 0
    attempts: int = 0
    approval: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "call_id": self.call_id,
            "tool": self.tool,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
        }
        if self.result is not None:
            payload["result"] = self.result
        if self.error:
            payload["error"] = self.error
            payload["error_kind"] = self.error_kind
        if self.approval:
            payload["approval"] = self.approval
        return payload


def validate_args(schema: Mapping[str, Any], args: Mapping[str, Any]) -> None:
    """轻量 JSON Schema 校验（够用即可，不引入 jsonschema 依赖）。

    校验 required、未定义参数、基础类型与 enum；复杂约束（format/pattern/anyOf）
    交给各工具自己。未定义参数必须拒绝：模型多塞一个字段不该悄悄落进 handler。
    """
    required = schema.get("required", [])
    missing = [k for k in required if k not in args]
    if missing:
        raise ToolError(ToolErrorKind.INVALID_ARGS, f"缺少必填参数: {', '.join(missing)}")

    props = schema.get("properties", {})
    if props and schema.get("additionalProperties", False) is not True:
        unknown = sorted(set(args) - set(props))
        if unknown:
            raise ToolError(ToolErrorKind.INVALID_ARGS, f"未定义参数: {', '.join(unknown)}")

    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    for key, value in args.items():
        spec = props.get(key)
        if not spec:
            continue
        expected = type_map.get(spec.get("type", ""))
        if expected and not isinstance(value, expected):
            raise ToolError(
                ToolErrorKind.INVALID_ARGS,
                f"参数 {key} 类型应为 {spec.get('type')}",
            )
        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ToolError(
                ToolErrorKind.INVALID_ARGS,
                f"参数 {key} 取值必须是: {', '.join(map(str, enum))}",
            )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not callable(spec.handler):
            raise ValueError("工具必须有 name 与 handler")
        if spec.name in self._tools:
            raise ValueError(f"工具重复注册: {spec.name}")
        self._tools[spec.name] = spec

    def try_get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def enabled_for(self, identity: Identity) -> list[ToolSpec]:
        return [
            s
            for s in self._tools.values()
            if s.enabled and (not s.roles or identity.roles.intersection(s.roles))
        ]

    def schema_for_model(self, identity: Identity) -> list[dict[str, Any]]:
        """给模型看的工具清单（只暴露该用户有权限的）。"""
        return [
            {"name": s.name, "description": s.description, "parameters": s.input_schema}
            for s in self.enabled_for(identity)
        ]


class ToolGuard:
    """五道闸门 + 超时 + 分类重试 + 降级标记。

    所有工具调用必须经过这里；禁止在 MCP server 内重复实现校验。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        approvers_role: str = "approver",
        backoff_base_ms: int = 200,
    ) -> None:
        self.registry = registry
        self.approvers_role = approvers_role
        self.backoff_base_ms = backoff_base_ms

    async def execute(
        self,
        name: str,
        args: Mapping[str, Any],
        identity: Identity,
        *,
        call_id: str,
        allow_write: bool = False,
    ) -> ToolCallResult:
        started = perf_counter()

        # ① 存在性：未注册即拒绝，且不暴露"有哪些工具"
        spec = self.registry.try_get(name)
        if spec is None:
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.DENIED,
                status=ToolStatus.DENIED,
                error_kind=ToolErrorKind.NOT_FOUND.value,
                error="工具未注册",
                duration_ms=_ms(started),
            )

        # ② 保留字段：身份只能由会话注入
        lowered = {str(k).lower() for k in args}
        reserved = sorted(RESERVED_ARGS.intersection(lowered))
        if reserved:
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.DENIED,
                status=ToolStatus.DENIED,
                error_kind=ToolErrorKind.PERMISSION.value,
                error=f"模型不得传入身份字段: {', '.join(reserved)}",
                duration_ms=_ms(started),
            )

        # ③ 权限
        if spec.roles and not identity.roles.intersection(spec.roles):
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.DENIED,
                status=ToolStatus.DENIED,
                error_kind=ToolErrorKind.PERMISSION.value,
                error="当前角色无权调用该工具",
                duration_ms=_ms(started),
            )

        # ④ 白名单 / 启用
        if not spec.enabled:
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.DENIED,
                status=ToolStatus.DENIED,
                error_kind=ToolErrorKind.PERMISSION.value,
                error="工具已禁用",
                duration_ms=_ms(started),
            )

        try:
            validate_args(spec.input_schema, args)
        except ToolError as exc:
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.EXECUTED,
                status=ToolStatus.ERROR,
                error_kind=exc.kind.value,
                error=exc.message,
                duration_ms=_ms(started),
                attempts=1,
            )

        # ⑤ 写操作：挂起，等人工审批（不是"再问模型一次"）
        if spec.is_write and not allow_write:
            return ToolCallResult(
                call_id=call_id,
                tool=name,
                decision=Decision.REQUIRES_APPROVAL,
                status=ToolStatus.REQUIRES_APPROVAL,
                result=None,
                duration_ms=_ms(started),
                approval={
                    "tool": name,
                    "args": dict(args),
                    "risk_level": "medium",
                    "approver_role": self.approvers_role,
                },
            )

        return await self._run_with_retry(
            spec, args, identity=identity, call_id=call_id, started=started
        )

    async def _run_with_retry(
        self,
        spec: ToolSpec,
        args: Mapping[str, Any],
        *,
        identity: Identity,
        call_id: str,
        started: float,
    ) -> ToolCallResult:
        last: ToolError = ToolError(ToolErrorKind.INTERNAL, "未执行")
        attempts = 0

        for attempt in range(1, spec.max_attempts + 1):
            attempts = attempt
            try:
                # asyncio.timeout 只保证"上层不再等"，handler 内部必须响应取消
                async with asyncio.timeout(spec.timeout_ms / 1000):
                    if spec.inject_identity:
                        result = await spec.handler(**args, identity=identity)
                    else:
                        result = await spec.handler(**args)
                return ToolCallResult(
                    call_id=call_id,
                    tool=spec.name,
                    decision=Decision.EXECUTED,
                    status=ToolStatus.OK,
                    result=result,
                    duration_ms=_ms(started),
                    attempts=attempts,
                )
            except TimeoutError:
                last = ToolError(ToolErrorKind.TIMEOUT, f"工具超时 {spec.timeout_ms}ms")
            except ToolError as exc:
                last = exc
            except Exception as exc:
                last = ToolError(ToolErrorKind.INTERNAL, str(exc))

            if not self._should_retry(spec, last, attempt):
                break
            await asyncio.sleep(self._backoff_seconds(attempt))

        status = ToolStatus.TIMEOUT if last.kind is ToolErrorKind.TIMEOUT else ToolStatus.ERROR
        return ToolCallResult(
            call_id=call_id,
            tool=spec.name,
            decision=Decision.EXECUTED,
            status=status,
            error_kind=last.kind.value,
            error=last.message,
            duration_ms=_ms(started),
            attempts=attempts,
        )

    def _should_retry(self, spec: ToolSpec, err: ToolError, attempt: int) -> bool:
        if attempt >= spec.max_attempts:
            return False
        if err.kind.value not in spec.retryable:
            return False
        # 写操作只在工具显式声明幂等安全时才允许重试
        return not (spec.is_write and not err.idempotent_safe)

    def _backoff_seconds(self, attempt: int) -> float:
        base = self.backoff_base_ms / 1000
        return base * (2 ** (attempt - 1)) * (0.5 + random.random())


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
