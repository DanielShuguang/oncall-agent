export const APPROVAL_STATS_WINDOW_STORAGE_KEY = 'oncall.approval-stats-window.v1';

export const APPROVAL_STATS_WINDOW_OPTIONS = [7, 30, 90] as const;

export type ApprovalStatsWindow = (typeof APPROVAL_STATS_WINDOW_OPTIONS)[number];

export type StatsWindowStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): StatsWindowStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalize(value: number): ApprovalStatsWindow {
  return (APPROVAL_STATS_WINDOW_OPTIONS as readonly number[]).includes(value)
    ? (value as ApprovalStatsWindow)
    : 7;
}

/** 只接受 7/30/90；缺失、损坏或存储不可用时回到 7 天。 */
export function readApprovalStatsWindow(
  storage: StatsWindowStorage | null = defaultStorage(),
): ApprovalStatsWindow {
  if (!storage) return 7;
  try {
    const raw = storage.getItem(APPROVAL_STATS_WINDOW_STORAGE_KEY);
    if (!raw) return 7;
    return normalize(Number(raw));
  } catch {
    return 7;
  }
}

export function writeApprovalStatsWindow(
  value: number,
  storage: StatsWindowStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    if (value === 7) {
      storage.removeItem(APPROVAL_STATS_WINDOW_STORAGE_KEY);
      return;
    }
    storage.setItem(APPROVAL_STATS_WINDOW_STORAGE_KEY, String(normalize(value)));
  } catch {
    // 本地偏好失败不能影响审批统计。
  }
}

export function clearApprovalStatsWindow(
  storage: StatsWindowStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(APPROVAL_STATS_WINDOW_STORAGE_KEY);
  } catch {
    // 同上。
  }
}
