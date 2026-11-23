export const APPROVAL_STATS_REFRESH_MS = 30_000;
export const DEFAULT_APPROVAL_STATS_REFRESH_SECONDS = 30;
export const APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS = [15, 30, 60] as const;
export const APPROVAL_STATS_REFRESH_INTERVAL_MIN = 5;
export const APPROVAL_STATS_REFRESH_INTERVAL_MAX = 300;
export type ApprovalStatsRefreshSeconds = number;

export const APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY = 'oncall.approval-stats-auto-refresh.v1';
export const APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY =
  'oncall.approval-stats-refresh-interval.v1';

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** 默认开启；只有明确的 `off` 才关闭，损坏值按默认处理。 */
export function readApprovalStatsAutoRefresh(
  storage: PreferenceStorage | null = defaultStorage(),
): boolean {
  if (!storage) return true;
  try {
    return storage.getItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function writeApprovalStatsAutoRefresh(
  enabled: boolean,
  storage: PreferenceStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY, enabled ? 'on' : 'off');
  } catch {
    // 隐私模式等存储不可用时保持内存态，不阻断页面。
  }
}

export function clearApprovalStatsAutoRefresh(
  storage: PreferenceStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY);
  } catch {
    // 同上。
  }
}

/** 默认 30 秒；接受 5–300 的整数，损坏/越界值按默认处理。 */
export function readApprovalStatsRefreshInterval(
  storage: PreferenceStorage | null = defaultStorage(),
): ApprovalStatsRefreshSeconds {
  if (!storage) return DEFAULT_APPROVAL_STATS_REFRESH_SECONDS;
  try {
    const value = Number(storage.getItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY));
    return Number.isInteger(value) &&
      value >= APPROVAL_STATS_REFRESH_INTERVAL_MIN &&
      value <= APPROVAL_STATS_REFRESH_INTERVAL_MAX
      ? value
      : DEFAULT_APPROVAL_STATS_REFRESH_SECONDS;
  } catch {
    return DEFAULT_APPROVAL_STATS_REFRESH_SECONDS;
  }
}

export function writeApprovalStatsRefreshInterval(
  seconds: ApprovalStatsRefreshSeconds,
  storage: PreferenceStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY, String(seconds));
  } catch {
    // 同上。
  }
}

export function clearApprovalStatsRefreshInterval(
  storage: PreferenceStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY);
  } catch {
    // 同上。
  }
}

function defaultStorage(): PreferenceStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

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
