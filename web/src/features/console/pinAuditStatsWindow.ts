export const PIN_AUDIT_STATS_WINDOW_STORAGE_KEY = 'oncall.pin-audit-stats-window.v1';

export const PIN_AUDIT_STATS_WINDOW_OPTIONS = [7, 30, 90] as const;

export type PinAuditStatsWindow = (typeof PIN_AUDIT_STATS_WINDOW_OPTIONS)[number];

export type StatsWindowStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): StatsWindowStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalize(value: number): PinAuditStatsWindow {
  return (PIN_AUDIT_STATS_WINDOW_OPTIONS as readonly number[]).includes(value)
    ? (value as PinAuditStatsWindow)
    : 30;
}

/** 只接受 7/30/90；缺失、损坏或存储不可用时回到 30 天。 */
export function readPinAuditStatsWindow(
  storage: StatsWindowStorage | null = defaultStorage(),
): PinAuditStatsWindow {
  if (!storage) return 30;
  try {
    const raw = storage.getItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY);
    if (!raw) return 30;
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'number' ? normalize(parsed) : 30;
  } catch {
    return 30;
  }
}

export function writePinAuditStatsWindow(
  value: number,
  storage: StatsWindowStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    if (value === 30) {
      storage.removeItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY);
      return;
    }
    storage.setItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY, String(normalize(value)));
  } catch {
    // 本地偏好失败不能影响审计页。
  }
}

export function clearPinAuditStatsWindow(
  storage: StatsWindowStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY);
  } catch {
    // 同上。
  }
}
