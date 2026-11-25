import type { ApprovalListFilters } from '@/api/approvals';

export const APPROVAL_FILTER_STORAGE_KEY = 'oncall.approval-filters.v1';

export interface ApprovalFilterMemory {
  tool: string;
  resolvedBy: string;
  resolvedFrom: string;
  resolvedTo: string;
}

type FilterStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const EMPTY: ApprovalFilterMemory = {
  tool: '',
  resolvedBy: '',
  resolvedFrom: '',
  resolvedTo: '',
};

function defaultStorage(): FilterStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function cleanId(value: unknown, max = 64): string {
  if (typeof value !== 'string') return '';
  const next = value.trim();
  return next.length > 0 && next.length <= max ? next : '';
}

function cleanDate(value: unknown): string {
  if (typeof value !== 'string') return '';
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : '';
}

function normalize(value: unknown): ApprovalFilterMemory {
  if (typeof value !== 'object' || value === null) return { ...EMPTY };
  const record = value as Record<string, unknown>;
  return {
    tool: cleanId(record.tool),
    resolvedBy: cleanId(record.resolvedBy),
    resolvedFrom: cleanDate(record.resolvedFrom),
    resolvedTo: cleanDate(record.resolvedTo),
  };
}

function isEmpty(value: ApprovalFilterMemory): boolean {
  return !value.tool && !value.resolvedBy && !value.resolvedFrom && !value.resolvedTo;
}

function toFilters(value: ApprovalFilterMemory): ApprovalListFilters {
  return {
    ...(value.tool ? { tool: value.tool } : {}),
    ...(value.resolvedBy ? { resolvedBy: value.resolvedBy } : {}),
    ...(value.resolvedFrom ? { resolvedFrom: value.resolvedFrom } : {}),
    ...(value.resolvedTo ? { resolvedTo: value.resolvedTo } : {}),
  };
}

export function filtersAfterStatusChange(
  nextStatus: string,
  currentStatus: string,
  currentFilters: ApprovalListFilters,
  readMemory: () => ApprovalListFilters = readApprovalFilterMemory,
): ApprovalListFilters {
  if (nextStatus === 'pending') return {};
  if (currentStatus === 'pending') return readMemory();
  return currentFilters;
}

export function readApprovalFilterMemory(
  storage: FilterStorage | null = defaultStorage(),
): ApprovalListFilters {
  if (!storage) return {};
  try {
    const raw = storage.getItem(APPROVAL_FILTER_STORAGE_KEY);
    if (!raw) return {};
    const value = normalize(JSON.parse(raw));
    if (isEmpty(value)) {
      storage.removeItem(APPROVAL_FILTER_STORAGE_KEY);
      return {};
    }
    return toFilters(value);
  } catch {
    return {};
  }
}

export function writeApprovalFilterMemory(
  filters: ApprovalListFilters,
  storage: FilterStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    const value = normalize(filters);
    if (isEmpty(value)) {
      storage.removeItem(APPROVAL_FILTER_STORAGE_KEY);
      return;
    }
    storage.setItem(APPROVAL_FILTER_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // 本地偏好失败不影响筛选本身。
  }
}

export function clearApprovalFilterMemory(storage: FilterStorage | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(APPROVAL_FILTER_STORAGE_KEY);
  } catch {
    // 本地偏好失败不影响筛选本身。
  }
}
