import { describe, expect, it } from 'vitest';
import { pinLimitOverflow } from './pinLimit';

describe('pinLimitOverflow', () => {
  it('未超限或计数未知时返回 null', () => {
    expect(pinLimitOverflow(null, 50)).toBeNull();
    expect(pinLimitOverflow(50, null)).toBeNull();
    expect(pinLimitOverflow(50, 50)).toBeNull();
    expect(pinLimitOverflow(49, 50)).toBeNull();
  });

  it('超过上限时返回实际计数与上限', () => {
    expect(pinLimitOverflow(51, 50)).toEqual({ pinned: 51, limit: 50 });
    expect(pinLimitOverflow(3, 2)).toEqual({ pinned: 3, limit: 2 });
  });

  it('上限非正数视为配置异常，不提示', () => {
    expect(pinLimitOverflow(10, 0)).toBeNull();
    expect(pinLimitOverflow(10, -1)).toBeNull();
  });
});
