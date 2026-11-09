"""文档级可见性（ADR-0019）。

规则只有一条，落在两个地方：

    is_visible()                       预览 / 管理接口（Python）
    PgKnowledgeStore._visibility_clause  召回（SQL，必须在 LIMIT 之前过滤）

两边必须等价。`tests/test_rag_acl.py` 用同一张 (visibility × 角色) 矩阵同时断言
内存实现、SQL 实现与 `is_visible()` 一致——改规则先改这里，再跑那组用例。

召回前过滤不是性能选择而是正确性选择：先取 20 条候选再丢掉不可见的，
等于让受限文档占掉候选名额、把可见文档挤出 top_k，调用方还会从
「命中数变化」推断出受限文档的存在。

`admin`（部署侧的 `ONCALL_ADMIN_ROLES`）是知识库所有者：本来就能上传、删除、
重建索引，再对它隐藏正文只是形式主义，也会让管理页的切片预览自相矛盾。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PUBLIC = "public"
ROLES = "roles"
VISIBILITIES = (PUBLIC, ROLES)

#: 角色是 JWT 里的字符串标签（没有 roles 表），这里只做语法校验，
#: 防止逗号/空格/中文被写进数组，导致「谁也匹配不上」的静默失效。
ROLE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
MAX_ROLES = 20


@dataclass(frozen=True, slots=True)
class Viewer:
    """调用者的可见范围；角色只能来自服务端会话（R9）。"""

    roles: frozenset[str] = frozenset()
    #: 知识库所有者（admin 角色）：跳过文档级过滤
    unrestricted: bool = False


def viewer_for(roles: Iterable[str], admin_roles: Sequence[str]) -> Viewer:
    held = frozenset(roles)
    return Viewer(roles=held, unrestricted=bool(held.intersection(admin_roles)))


def is_visible(*, visibility: str, allowed_roles: Sequence[str], viewer: Viewer) -> bool:
    """`public` 对所有登录用户可见；`roles` 需要角色交集；所有者不受限。"""
    if viewer.unrestricted or visibility == PUBLIC:
        return True
    return not viewer.roles.isdisjoint(allowed_roles)


def parse_access(
    visibility: str,
    allowed_roles: Iterable[str] | str = (),
) -> tuple[str, tuple[str, ...]]:
    """校验并规范化接口入参，返回 `(visibility, allowed_roles)`。

    同时接受逗号分隔字符串（multipart 表单）与序列（JSON 请求体）；
    空角色名直接忽略，重复角色去重保序。校验失败抛 `ValueError`，由接口层转 422。
    """
    normalized = str(visibility).strip().lower()
    if normalized not in VISIBILITIES:
        raise ValueError(f"可见性只能是 {' / '.join(VISIBILITIES)}")

    raw = allowed_roles.split(",") if isinstance(allowed_roles, str) else allowed_roles
    roles: list[str] = []
    for item in raw:
        role = str(item).strip()
        if not role:
            continue
        if not ROLE_PATTERN.match(role):
            raise ValueError(f"角色名不合法: {role}（字母、数字、_ . -，最长 32）")
        if role not in roles:
            roles.append(role)

    if len(roles) > MAX_ROLES:
        raise ValueError(f"角色最多 {MAX_ROLES} 个")
    if normalized == PUBLIC and roles:
        raise ValueError("公开文档不能指定角色")
    if normalized == ROLES and not roles:
        raise ValueError("指定角色可见时至少要填一个角色")
    return normalized, tuple(roles)
