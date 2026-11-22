import { describe, expect, it } from 'vitest';
import { describeSnapshot } from './toolHistoryFormat';

describe('describeSnapshot', () => {
  it('null 表示代码默认', () => {
    expect(describeSnapshot(null)).toBe('代码默认');
  });

  it('enabled/roles 都为 null 时继承', () => {
    expect(describeSnapshot({ enabled: null, roles: null })).toBe('启用继承 · 角色继承');
  });

  it('禁用且角色为空表示所有登录用户', () => {
    expect(describeSnapshot({ enabled: false, roles: [] })).toBe('禁用 · 所有登录用户');
  });

  it('多角色按顿号连接', () => {
    expect(describeSnapshot({ enabled: true, roles: ['admin', 'approver'] })).toBe(
      '启用 · admin、approver',
    );
  });
});
