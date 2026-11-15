/** 审计页记住用户/会话过滤与统计窗口（ADR-0078）。 */

export const AUDIT_FILTER_MEMORY_KEY = 'oncall.audit-filters.v1';

export const AUDIT_STATS_DAYS = [7, 30, 90] as const;

export type AuditStatsDays = (typeof AUDIT_STATS_DAYS)[number];

export interface AuditFilterMemory {
  userId: string;
  sessionId: string;
  statsDays: AuditStatsDays;
}

type FilterStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultFilterStorage(): FilterStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isStatsDays(value: unknown): value is AuditStatsDays {
  return typeof value === 'number' && AUDIT_STATS_DAYS.includes(value as AuditStatsDays);
}

function readId(value: unknown): string | null {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length <= 64 ? trimmed : null;
}

export function readAuditFilterMemory(
  storage: FilterStorage | null = defaultFilterStorage(),
): AuditFilterMemory | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(AUDIT_FILTER_MEMORY_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    const userId = readId(record.userId);
    const sessionId = readId(record.sessionId);
    if (userId === null || sessionId === null) return null;
    const statsDays = isStatsDays(record.statsDays) ? record.statsDays : 30;
    if (!userId && !sessionId && statsDays === 30) return null;
    return { userId, sessionId, statsDays };
  } catch {
    return null;
  }
}

export function writeAuditFilterMemory(
  memory: AuditFilterMemory,
  storage: FilterStorage | null = defaultFilterStorage(),
): void {
  if (!storage) return;
  const userId = memory.userId.trim();
  const sessionId = memory.sessionId.trim();
  if (userId.length > 64 || sessionId.length > 64 || !isStatsDays(memory.statsDays)) return;
  try {
    if (!userId && !sessionId && memory.statsDays === 30) {
      storage.removeItem(AUDIT_FILTER_MEMORY_KEY);
      return;
    }
    storage.setItem(
      AUDIT_FILTER_MEMORY_KEY,
      JSON.stringify({ userId, sessionId, statsDays: memory.statsDays }),
    );
  } catch {
    // 隐私模式或配额不足时不影响筛选本身。
  }
}

export function clearAuditFilterMemory(
  storage: FilterStorage | null = defaultFilterStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(AUDIT_FILTER_MEMORY_KEY);
  } catch {
    // 存储不可用时不阻断清除筛选。
  }
}
