/**
 * 知识库文档可见范围（ADR-0019）的纯函数。
 *
 * 规则以后端 `app/rag/access.py` 为准；这里只做展示文案与「提交前可读的报错」，
 * 不做权限判定——前端算出来的可见性一律不可信。
 */

export type Visibility = 'public' | 'roles';

export interface KbAccessLike {
  visibility: string;
  allowed_roles: string[];
}

/** 与后端 ROLE_PATTERN / MAX_ROLES 对齐；不一致时后端仍会兜底返回 422。 */
const ROLE_PATTERN = /^[A-Za-z0-9_.-]{1,32}$/;
export const MAX_ROLES = 20;

/**
 * 把「逗号分隔的角色输入」解析成数组。
 * 空输入返回空数组且不报错：由调用方决定「公开可以空、指定角色不能空」。
 */
export function parseRoleInput(text: string): { roles: string[]; error: string | null } {
  const roles: string[] = [];
  for (const raw of text.split(',')) {
    const role = raw.trim();
    if (!role) continue;
    if (!ROLE_PATTERN.test(role)) {
      return { roles: [], error: `角色名不合法：${role}（字母、数字、_ . -，最长 32）` };
    }
    if (!roles.includes(role)) roles.push(role);
  }
  if (roles.length > MAX_ROLES) {
    return { roles: [], error: `角色最多 ${MAX_ROLES} 个` };
  }
  return { roles, error: null };
}

/** 列表与详情里的可见范围标签；未知值不假装成「公开」。 */
export function accessLabel(access: KbAccessLike): string {
  if (access.visibility === 'public') return '公开';
  if (access.visibility !== 'roles') return `未知（${access.visibility}）`;
  const roles = access.allowed_roles ?? [];
  return roles.length === 0 ? '指定角色（未配置）' : `仅 ${roles.join('、')}`;
}

export function isRestricted(access: KbAccessLike): boolean {
  return access.visibility !== 'public';
}

/**
 * 编辑弹窗的初始状态。
 * 除 `public` 外一律按 `roles` 打开：roles 至少一个角色，保存时会被校验，
 * 这样未知值/脏数据不会被静默改写成「公开」。
 */
export function draftOf(access: KbAccessLike): { visibility: Visibility; rolesText: string } {
  return {
    visibility: access.visibility === 'public' ? 'public' : 'roles',
    rolesText: (access.allowed_roles ?? []).join(','),
  };
}
