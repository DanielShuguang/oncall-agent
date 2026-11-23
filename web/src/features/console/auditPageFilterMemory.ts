/** 置顶/导出审计页记住非日期过滤（ADR-0119）；日期预设由 ADR-0118 单独负责。 */

import { EXPORT_RESOURCE_LABEL, type ExportResource } from '@/api/exportAudits';
import type { SessionPinAction } from '@/api/pinAudits';

export const PIN_AUDIT_FILTER_STORAGE_KEY = 'oncall.pin-audit-filters.v1';
export const EXPORT_AUDIT_FILTER_STORAGE_KEY = 'oncall.export-audit-filters.v1';

const MAX_FILTER_LENGTH = 64;
const PIN_ACTIONS = new Set<SessionPinAction>(['pin', 'unpin']);

type FilterStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export type PinAuditFilterMemory = {
  userId: string;
  sessionId: string;
  action: 'all' | SessionPinAction;
};

export type ExportAuditFilterMemory = {
  userId: string;
  resource: '' | ExportResource;
};

function defaultStorage(): FilterStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function cleanId(value: unknown): string {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_FILTER_LENGTH ? trimmed : '';
}

function parseRecord(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function isPinAction(value: unknown): value is SessionPinAction {
  return typeof value === 'string' && PIN_ACTIONS.has(value as SessionPinAction);
}

function isExportResource(value: unknown): value is ExportResource {
  return typeof value === 'string' && Object.hasOwn(EXPORT_RESOURCE_LABEL, value);
}

export function readPinAuditFilterMemory(
  storage: FilterStorage | null = defaultStorage(),
): PinAuditFilterMemory | null {
  if (!storage) return null;
  try {
    const parsed = parseRecord(storage.getItem(PIN_AUDIT_FILTER_STORAGE_KEY));
    if (!parsed) return null;
    const userId = cleanId(parsed.userId);
    const sessionId = cleanId(parsed.sessionId);
    const action = isPinAction(parsed.action) ? parsed.action : 'all';
    return userId || sessionId || action !== 'all' ? { userId, sessionId, action } : null;
  } catch {
    return null;
  }
}

export function writePinAuditFilterMemory(
  memory: PinAuditFilterMemory,
  storage: FilterStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  const userId = cleanId(memory.userId);
  const sessionId = cleanId(memory.sessionId);
  const action = isPinAction(memory.action) ? memory.action : 'all';
  try {
    if (!userId && !sessionId && action === 'all') {
      storage.removeItem(PIN_AUDIT_FILTER_STORAGE_KEY);
      return;
    }
    storage.setItem(PIN_AUDIT_FILTER_STORAGE_KEY, JSON.stringify({ userId, sessionId, action }));
  } catch {
    // 存储不可用时静默降级；当前筛选仍然生效。
  }
}

export function clearPinAuditFilterMemory(storage: FilterStorage | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(PIN_AUDIT_FILTER_STORAGE_KEY);
  } catch {
    // 清理失败不影响页面状态。
  }
}

export function readExportAuditFilterMemory(
  storage: FilterStorage | null = defaultStorage(),
): ExportAuditFilterMemory | null {
  if (!storage) return null;
  try {
    const parsed = parseRecord(storage.getItem(EXPORT_AUDIT_FILTER_STORAGE_KEY));
    if (!parsed) return null;
    const userId = cleanId(parsed.userId);
    const resource = isExportResource(parsed.resource) ? parsed.resource : '';
    return userId || resource ? { userId, resource } : null;
  } catch {
    return null;
  }
}

export function writeExportAuditFilterMemory(
  memory: ExportAuditFilterMemory,
  storage: FilterStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  const userId = cleanId(memory.userId);
  const resource = isExportResource(memory.resource) ? memory.resource : '';
  try {
    if (!userId && !resource) {
      storage.removeItem(EXPORT_AUDIT_FILTER_STORAGE_KEY);
      return;
    }
    storage.setItem(EXPORT_AUDIT_FILTER_STORAGE_KEY, JSON.stringify({ userId, resource }));
  } catch {
    // 同 PIN：存储失败只影响记忆，不影响筛选。
  }
}

export function clearExportAuditFilterMemory(
  storage: FilterStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(EXPORT_AUDIT_FILTER_STORAGE_KEY);
  } catch {
    // 清理失败不影响页面状态。
  }
}
