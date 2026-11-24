import type { StatsGroup } from './approvalTypes';

export const APPROVAL_STATS_GROUP_STORAGE_KEY = 'oncall.approval-stats-group.v1';

export const APPROVAL_STATS_GROUP_OPTIONS = ['none', 'tool', 'approver'] as const;

export type StatsGroupStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): StatsGroupStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalize(value: string): StatsGroup {
  return (APPROVAL_STATS_GROUP_OPTIONS as readonly string[]).includes(value)
    ? (value as StatsGroup)
    : 'none';
}

/** 只接受 none/tool/approver；缺失、损坏或存储不可用时回到不分组。 */
export function readApprovalStatsGroup(
  storage: StatsGroupStorage | null = defaultStorage(),
): StatsGroup {
  if (!storage) return 'none';
  try {
    const raw = storage.getItem(APPROVAL_STATS_GROUP_STORAGE_KEY);
    if (!raw) return 'none';
    return normalize(raw);
  } catch {
    return 'none';
  }
}

export function writeApprovalStatsGroup(
  value: string,
  storage: StatsGroupStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    const normalized = normalize(value);
    if (normalized === 'none') {
      storage.removeItem(APPROVAL_STATS_GROUP_STORAGE_KEY);
      return;
    }
    storage.setItem(APPROVAL_STATS_GROUP_STORAGE_KEY, normalized);
  } catch {
    // 本地偏好失败不能影响审批统计。
  }
}

export function clearApprovalStatsGroup(
  storage: StatsGroupStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(APPROVAL_STATS_GROUP_STORAGE_KEY);
  } catch {
    // 同上。
  }
}
