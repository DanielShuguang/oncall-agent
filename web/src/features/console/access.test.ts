import { describe, expect, it } from 'vitest';
import { MAX_ROLES, accessLabel, draftOf, isRestricted, parseRoleInput } from './access';

describe('parseRoleInput', () => {
  it('去空格、去空项、按原顺序去重', () => {
    expect(parseRoleInput(' hr , finance,hr , ')).toEqual({
      roles: ['hr', 'finance'],
      error: null,
    });
    expect(parseRoleInput('')).toEqual({ roles: [], error: null });
  });

  it('拒绝后端也无法接受的角色名', () => {
    expect(parseRoleInput('hr admin').error).toContain('角色名不合法');
    expect(parseRoleInput('人事').error).toContain('角色名不合法');
    expect(parseRoleInput(`${'x'.repeat(33)}`).error).toContain('角色名不合法');
  });

  it('超过上限时给可读文案，而不是等后端 422', () => {
    const text = Array.from({ length: MAX_ROLES + 1 }, (_, index) => `r${index}`).join(',');
    expect(parseRoleInput(text).roles).toEqual([]);
    expect(parseRoleInput(text).error).toBe(`角色最多 ${MAX_ROLES} 个`);
  });
});

describe('accessLabel', () => {
  it('公开与指定角色分开显示', () => {
    expect(accessLabel({ visibility: 'public', allowed_roles: [] })).toBe('公开');
    expect(accessLabel({ visibility: 'roles', allowed_roles: ['hr', 'finance'] })).toBe(
      '仅 hr、finance',
    );
  });

  it('roles 但没有角色（历史脏数据）不能显示成公开', () => {
    expect(accessLabel({ visibility: 'roles', allowed_roles: [] })).toBe('指定角色（未配置）');
    expect(isRestricted({ visibility: 'roles', allowed_roles: [] })).toBe(true);
  });

  it('未知可见性不假装成公开', () => {
    expect(accessLabel({ visibility: 'team', allowed_roles: [] })).toBe('未知（team）');
  });
});

describe('draftOf', () => {
  it('公开文档打开为公开，角色文档带回原有角色', () => {
    expect(draftOf({ visibility: 'public', allowed_roles: [] })).toEqual({
      visibility: 'public',
      rolesText: '',
    });
    expect(draftOf({ visibility: 'roles', allowed_roles: ['hr', 'finance'] })).toEqual({
      visibility: 'roles',
      rolesText: 'hr,finance',
    });
  });

  it('未知可见性按 roles 打开，保存时必须重新填角色（不能静默变公开）', () => {
    expect(draftOf({ visibility: 'team', allowed_roles: [] })).toEqual({
      visibility: 'roles',
      rolesText: '',
    });
  });
});
