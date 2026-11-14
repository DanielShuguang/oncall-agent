import { describe, expect, it } from 'vitest';

import { formatRestoreNotice } from './restoreNotice';

function item(sessionId: string, restored: boolean) {
  return { session_id: sessionId, restored };
}

describe('formatRestoreNotice', () => {
  it('全部成功时只报恢复数量', () => {
    expect(formatRestoreNotice(2, [item('a', true), item('b', true)])).toBe('已恢复 2 个会话。');
  });

  it('部分成功时报未恢复数量并解释原因', () => {
    expect(formatRestoreNotice(2, [item('a', true), item('b', true), item('c', false)])).toBe(
      '已恢复 2 个会话；1 个未恢复（可能已被恢复或不在本人已移除列表）。',
    );
  });

  it('全部未恢复时不再说「已恢复 0 个」', () => {
    expect(formatRestoreNotice(0, [item('a', false), item('b', false)])).toBe(
      '没有会话被恢复；2 个未恢复（可能已被恢复或不在本人已移除列表）。',
    );
  });

  it('旧后端没有 items 时仍按计数给出结果', () => {
    expect(formatRestoreNotice(3, undefined)).toBe('已恢复 3 个会话。');
    expect(formatRestoreNotice(0, undefined)).toBe('没有会话被恢复。');
  });
});
