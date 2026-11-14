/** 会话恢复审计接口：契约见 docs/03 §5（ADR-0059/0060/0061/0062/0065/0067）。 */

import { getFile, getJson } from './client';

export interface SessionRestoreAudit {
  id: string;
  user_id: string;
  session_ids: string[];
  requested_count: number;
  restored_count: number;
  restored_at: string;
}

export interface SessionRestoreAuditListResponse {
  items: SessionRestoreAudit[];
  /** 取满 `limit` 时给下一页游标；否则为 null（ADR-0060）。 */
  next_cursor: string | null;
  /** 第一页返回同过滤条件总数；后续页/旧后端为 null 或缺失（ADR-0064）。 */
  total?: number | null;
}

export interface SessionRestoreAuditFilters {
  userId?: string;
  sessionId?: string;
  /** UTC 自然日闭区间起始（ADR-0067）；必须与 restoredTo 同时提供。 */
  restoredFrom?: string;
  /** UTC 自然日闭区间结束（ADR-0067）。 */
  restoredTo?: string;
}

export interface SessionRestoreAuditExport {
  blob: Blob;
  count: number;
  /** 服务端最多导出 5000 条；超出时只含当前排序的前 5000 条（ADR-0062）。 */
  truncated: boolean;
}

export interface SessionRestoreAuditDayStats {
  /** UTC 自然日，ISO `YYYY-MM-DD`；只含有恢复活动的日期（ADR-0065）。 */
  day: string;
  restores: number;
  sessions: number;
}

export interface SessionRestoreAuditStats {
  days: number;
  since: string;
  until: string;
  restores: number;
  users: number;
  sessions: number;
  daily: SessionRestoreAuditDayStats[];
}

function applyFilters(params: URLSearchParams, filters: SessionRestoreAuditFilters): void {
  if (filters.userId) params.set('user_id', filters.userId);
  if (filters.sessionId) params.set('session_id', filters.sessionId);
  if (filters.restoredFrom) params.set('restored_from', filters.restoredFrom);
  if (filters.restoredTo) params.set('restored_to', filters.restoredTo);
}

export function listSessionRestoreAudits(
  filters: SessionRestoreAuditFilters = {},
  cursor: string | null = null,
  limit = 20,
): Promise<SessionRestoreAuditListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  applyFilters(params, filters);
  return getJson<SessionRestoreAuditListResponse>(`/admin/session-restores?${params.toString()}`);
}

export async function exportSessionRestoreAuditsCsv(
  filters: SessionRestoreAuditFilters = {},
): Promise<SessionRestoreAuditExport> {
  const params = new URLSearchParams();
  applyFilters(params, filters);
  const query = params.toString();
  const { blob, headers } = await getFile(
    `/admin/session-restores/export${query ? `?${query}` : ''}`,
  );
  return {
    blob,
    count: Number(headers.get('X-Export-Count') ?? 0) || 0,
    truncated: headers.get('X-Export-Truncated') === 'true',
  };
}

export function getSessionRestoreAuditStats(
  days: number | null,
  filters: SessionRestoreAuditFilters = {},
): Promise<SessionRestoreAuditStats> {
  const params = new URLSearchParams();
  // 自定义日期范围本身决定窗口；服务端拒绝 days 与范围同时出现（ADR-0067）。
  const hasRange = Boolean(filters.restoredFrom && filters.restoredTo);
  if (!hasRange) params.set('days', String(days ?? 30));
  applyFilters(params, filters);
  return getJson<SessionRestoreAuditStats>(`/admin/session-restores/stats?${params.toString()}`);
}
