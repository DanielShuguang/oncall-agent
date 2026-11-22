import { describe, expect, it } from 'vitest';
import {
  APPROVAL_STATS_REFRESH_MS,
  formatStatsUpdatedAt,
  shouldAutoRefresh,
} from './approvalStatsRefresh';

describe('approvalStatsRefresh', () => {
  it('每 30 秒刷新一次', () => {
    expect(APPROVAL_STATS_REFRESH_MS).toBe(30_000);
  });

  it('只在页面可见时自动刷新', () => {
    expect(shouldAutoRefresh('visible')).toBe(true);
    expect(shouldAutoRefresh('hidden')).toBe(false);
  });

  it('没有更新时不伪造时间', () => {
    expect(formatStatsUpdatedAt(null)).toBe('尚未更新');
    expect(formatStatsUpdatedAt(0)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});
