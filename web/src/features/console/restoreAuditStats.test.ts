import { describe, expect, it } from 'vitest';
import { countUnrestoredPins } from './restoreAuditStats';

describe('countUnrestoredPins', () => {
  it('返回恢复会话中未恢复置顶的数量', () => {
    expect(countUnrestoredPins({ sessions: 5, repinned: 3 })).toBe(2);
  });

  it('全部恢复置顶时为 0', () => {
    expect(countUnrestoredPins({ sessions: 3, repinned: 3 })).toBe(0);
  });

  it('异常的大 repinned 值不会产生负数', () => {
    expect(countUnrestoredPins({ sessions: 2, repinned: 3 })).toBe(0);
  });
});
