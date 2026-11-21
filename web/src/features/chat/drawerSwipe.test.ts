import { describe, expect, it } from 'vitest';
import { isDrawerSwipeClose } from './drawerSwipe';

describe('isDrawerSwipeClose', () => {
  it('左滑达到阈值且水平占优时关闭', () => {
    expect(isDrawerSwipeClose(-80, 10)).toBe(true);
    expect(isDrawerSwipeClose(-160, 20)).toBe(true);
  });

  it('位移不够时不关闭', () => {
    expect(isDrawerSwipeClose(-79, 0)).toBe(false);
    expect(isDrawerSwipeClose(0, 0)).toBe(false);
  });

  it('向右或垂直滚动不关闭', () => {
    expect(isDrawerSwipeClose(100, 10)).toBe(false);
    expect(isDrawerSwipeClose(-100, 120)).toBe(false);
  });

  it('斜向但水平不占优时不关闭', () => {
    expect(isDrawerSwipeClose(-90, -90)).toBe(false);
    expect(isDrawerSwipeClose(-90, 61)).toBe(false);
  });
});
