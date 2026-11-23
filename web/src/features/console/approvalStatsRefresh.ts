export const APPROVAL_STATS_REFRESH_MS = 30_000;

/** 只在页面可见时轮询，避免后台标签页持续打接口。 */
export function shouldAutoRefresh(visibility: DocumentVisibilityState, enabled = true): boolean {
  return enabled && visibility === 'visible';
}

export function formatStatsUpdatedAt(value: number | null): string {
  if (value === null) return '尚未更新';
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
