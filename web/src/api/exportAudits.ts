/** CSV 导出下载审计接口：契约见 docs/03 §3.3.3（ADR-0094）。 */

import { getJson } from './client';

export type ExportResource =
  | 'approvals'
  | 'approval_stats'
  | 'session_restores'
  | 'session_restore_stats'
  | 'session_pins'
  | 'session_pin_stats';

export const EXPORT_RESOURCE_LABEL: Record<ExportResource, string> = {
  approvals: '审批列表',
  approval_stats: '审批统计',
  session_restores: '恢复审计列表',
  session_restore_stats: '恢复审计统计',
  session_pins: '置顶审计列表',
  session_pin_stats: '置顶审计统计',
};

export interface ExportAudit {
  id: string;
  user_id: string;
  resource: ExportResource;
  /** 已应用过滤条件；空对象表示无过滤。 */
  filters: Record<string, string>;
  row_count: number;
  truncated: boolean;
  created_at: string;
}

export interface ExportAuditListResponse {
  items: ExportAudit[];
  /** 取满 `limit` 时给下一页游标；否则为 null。 */
  next_cursor: string | null;
  /** 第一页返回同过滤总数；后续页为 null（旧后端无字段）。 */
  total?: number | null;
}

export interface ExportAuditFilters {
  userId?: string;
  resource?: ExportResource;
  /** UTC 自然日闭区间；两端同时提供。 */
  createdFrom?: string;
  createdTo?: string;
}

export function listExportAudits(
  filters: ExportAuditFilters = {},
  cursor: string | null = null,
  limit = 20,
): Promise<ExportAuditListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  if (filters.userId) params.set('user_id', filters.userId);
  if (filters.resource) params.set('resource', filters.resource);
  if (filters.createdFrom) params.set('created_from', filters.createdFrom);
  if (filters.createdTo) params.set('created_to', filters.createdTo);
  return getJson<ExportAuditListResponse>(`/admin/export-audits?${params.toString()}`);
}
