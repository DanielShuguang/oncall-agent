import type { RestoreSessionsItem } from '@/api/sessions';

const FAILED_HINT = '（可能已被恢复或不在本人已移除列表）';

/**
 * 批量恢复后的中性提示（ADR-0055）。
 *
 * `items` 允许缺省：滚动升级时新前端可能先于后端上线，旧响应没有逐条结果，
 * 此时只展示仍可信的 `restored` 计数，不能因为少一个字段把成功的恢复报成失败。
 */
export function formatRestoreNotice(
  restored: number,
  items: RestoreSessionsItem[] | undefined,
): string {
  if (items === undefined) {
    return restored > 0 ? `已恢复 ${restored} 个会话。` : '没有会话被恢复。';
  }
  const failed = items.filter((item) => !item.restored).length;
  if (failed === 0) return `已恢复 ${restored} 个会话。`;
  if (restored === 0) return `没有会话被恢复；${failed} 个未恢复${FAILED_HINT}。`;
  return `已恢复 ${restored} 个会话；${failed} 个未恢复${FAILED_HINT}。`;
}
