"""v1 角色目录（W5 D23）。

没有独立的 `roles` 表：v1 的角色是 JWT 里的字符串，部署时由 `ONCALL_ADMIN_ROLES`
与 `ONCALL_APPROVER_ROLES` 配置特殊角色。权限矩阵页需要一份可见的角色清单，
这里把「内置角色 + 配置里的管理/审批角色」合并，避免配了自定义角色却不在矩阵里。
"""

from __future__ import annotations

from app.core.config import Settings

#: 内置角色：employee 是普通员工，其余是治理角色
V1_ROLES: tuple[str, ...] = ("employee", "approver", "admin")


def role_catalog(settings: Settings) -> list[str]:
    roles = list(V1_ROLES)
    for name in (*settings.admin_role_list, *settings.approver_role_list):
        if name and name not in roles:
            roles.append(name)
    return roles
