/** 置顶审计接口：契约见 docs/03 §3.3.2（ADR-0081/0082/0084/0086）。 */

import { getFile, getJson } from './client';

export type SessionPinAction = 'pin' | 'unpin';

export interface SessionPinAudit {
  id: string;
  user_id: string;
  session_id: string;
  action: SessionPinAction;
  created_at: string;
}

export interface SessionPinAuditListResponse {
  items: SessionPinAudit[];
  /** 取满 `limit` 时给下一页游标；否则为 null（ADR-0082）。 */
  next_cursor: string | null;
}

export interface SessionPinAuditFilters {
  userId?: string;
  sessionId?: string;
  action?: SessionPinAction;
  /** UTC 自然日闭区间；两端同时提供（ADR-0086）。 */
  createdFrom?: string;
  createdTo?: string;
}

export interface SessionPinAuditExport {
  blob: Blob;
  count: number;
  /** 服务端最多导出 5000 条；超出时只含当前排序的前 5000 条（ADR-0084）。 */
  truncated: boolean;
}

function applyFilters(params: URLSearchParams, filters: SessionPinAuditFilters): void {
  if (filters.userId) params.set('user_id', filters.userId);
  if (filters.sessionId) params.set('session_id', filters.sessionId);
  if (filters.action) params.set('action', filters.action);
  if (filters.createdFrom && filters.createdTo) {
    params.set('created_from', filters.createdFrom);
    params.set('created_to', filters.createdTo);
  }
}

export function listSessionPinAudits(
  filters: SessionPinAuditFilters = {},
  cursor: string | null = null,
  limit = 20,
): Promise<SessionPinAuditListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  applyFilters(params, filters);
  return getJson<SessionPinAuditListResponse>(`/admin/session-pins?${params.toString()}`);
}

export async function exportSessionPinAuditsCsv(
  filters: SessionPinAuditFilters = {},
): Promise<SessionPinAuditExport> {
  const params = new URLSearchParams();
  applyFilters(params, filters);
  const query = params.toString();
  const { blob, headers } = await getFile(`/admin/session-pins/export${query ? `?${query}` : ''}`);
  return {
    blob,
    count: Number(headers.get('X-Export-Count') ?? 0) || 0,
    truncated: headers.get('X-Export-Truncated') === 'true',
  };
}
