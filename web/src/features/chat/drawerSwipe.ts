/**
 * 窄屏会话抽屉的左滑关闭判定。
 *
 * 抽屉从左侧滑出，因此只有向左（dx < 0）且水平位移明显大于垂直位移时才关闭；
 * 向上/下滚动列表不应误触。只判断松手后的总位移，不做实时跟手动画（ADR-0104）。
 */

export const DRAWER_SWIPE_CLOSE_PX = 80;
const HORIZONTAL_DOMINANCE = 1.5;

export function isDrawerSwipeClose(dx: number, dy: number): boolean {
  return dx <= -DRAWER_SWIPE_CLOSE_PX && Math.abs(dx) >= Math.abs(dy) * HORIZONTAL_DOMINANCE;
}
