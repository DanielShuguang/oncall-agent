/** 审批接口：契约见 docs/03-api-contract.md §4。 */

import { getFile, getJson } from './client';

export interface ApprovalOut {
  approval_id: string;
  run_id: string;
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk_level: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  requested_by: string;
  resolved_by?: string | null;
  reason?: string | null;
  scope: string;
  expires_at: string;
  created_at: string;
  resolved_at?: string | null;
}

export interface ApprovalListResponse {
  items: ApprovalOut[];
  /** 当前页取满时返回的 keyset 游标；没有更多为 null（ADR-0052） */
  next_cursor: string | null;
  /** 第一页返回总数；后续页为 null，旧后端可能没有该字段（ADR-0057） */
  total?: number | null;
}

export interface ApprovalDayStats {
  /** UTC 日期，YYYY-MM-DD；只含窗口内真正有决议的日期（ADR-0050） */
  day: string;
  decided_count: number;
  avg_wait_ms: number | null;
}

export interface ApprovalHourStats {
  /** UTC 小时 0–23；只含有决议的小时（ADR-0058） */
  hour: number;
  decided_count: number;
  avg_wait_ms: number | null;
}

export interface ApprovalGroupStats {
  /** 分组键：工具名，或审批人 user_id（缺失时为 unknown，ADR-0051） */
  key: string;
  decided_count: number;
  avg_wait_ms: number | null;
  max_wait_ms: number | null;
}

export interface ApprovalStats {
  days: number;
  pending_count: number;
  oldest_pending_age_s: number | null;
  decided_count: number;
  avg_wait_ms: number | null;
  max_wait_ms: number | null;
  daily: ApprovalDayStats[];
  hourly: ApprovalHourStats[];
  groups: ApprovalGroupStats[];
  groups_truncated: boolean;
}

export interface ApprovalResolveResponse {
  approval: ApprovalOut;
  run_id: string;
  run_status: string | null;
}

export type ApprovalDecision = 'approved' | 'rejected';
export type ApprovalScope = 'once' | 'session';

/** 已办筛选（ADR-0054）：日期是 UTC 自然日，start/end 由后端转成半开区间。 */
export interface ApprovalListFilters {
  tool?: string;
  resolvedBy?: string;
  resolvedFrom?: string;
  resolvedTo?: string;
}

function applyApprovalFilters(params: URLSearchParams, filters: ApprovalListFilters): void {
  if (filters.tool) params.set('tool', filters.tool);
  if (filters.resolvedBy) params.set('resolved_by', filters.resolvedBy);
  if (filters.resolvedFrom) params.set('resolved_from', filters.resolvedFrom);
  if (filters.resolvedTo) params.set('resolved_to', filters.resolvedTo);
}

export function listApprovals(
  status = 'pending',
  cursor: string | null = null,
  limit = 50,
  filters: ApprovalListFilters = {},
): Promise<ApprovalListResponse> {
  const params = new URLSearchParams({ status, limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  applyApprovalFilters(params, filters);
  return getJson<ApprovalListResponse>(`/approvals?${params.toString()}`);
}

export interface ApprovalExport {
  blob: Blob;
  count: number;
  /** 服务端最多导出 5000 条；超出时只返回当前排序的前 5000 条（ADR-0056）。 */
  truncated: boolean;
}

export async function exportApprovalsCsv(
  status = 'pending',
  filters: ApprovalListFilters = {},
): Promise<ApprovalExport> {
  const params = new URLSearchParams({ status });
  applyApprovalFilters(params, filters);
  const { blob, headers } = await getFile(`/approvals/export?${params.toString()}`);
  return {
    blob,
    count: Number(headers.get('X-Export-Count') ?? 0) || 0,
    truncated: headers.get('X-Export-Truncated') === 'true',
  };
}

export function getApprovalStats(
  days = 7,
  groupBy: 'tool' | 'approver' | null = null,
): Promise<ApprovalStats> {
  const params = new URLSearchParams({ days: String(days) });
  if (groupBy !== null) params.set('group_by', groupBy);
  return getJson<ApprovalStats>(`/approvals/stats?${params.toString()}`);
}

export function resolveApproval(
  approvalId: string,
  decision: ApprovalDecision,
  options: { reason?: string; scope?: ApprovalScope } = {},
): Promise<ApprovalResolveResponse> {
  return getJson<ApprovalResolveResponse>(`/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: 'POST',
    body: JSON.stringify({
      decision,
      reason: options.reason,
      scope: options.scope ?? 'once',
    }),
  });
}
