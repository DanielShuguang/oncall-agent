/** 恢复审计统计的派生值（ADR-0111）。 */

import type { SessionRestoreAuditStats } from '@/api/sessionAudits';

/**
 * 统计窗口内「恢复了但没有置顶」的会话数。
 *
 * 只能说明未置顶，不能区分「原本就没置顶」和「置顶容量不足」；ADR-0109 的
 * `repinned_count` 只记实际恢复的置顶数，没有记录原置顶意图。
 */
export function countUnrestoredPins(
  stats: Pick<SessionRestoreAuditStats, 'sessions' | 'repinned'>,
): number {
  return Math.max(0, stats.sessions - stats.repinned);
}
