/** 审批接口：契约见 docs/03-api-contract.md §4。 */

import { getJson } from './client';

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
}

export interface ApprovalStats {
  days: number;
  pending_count: number;
  oldest_pending_age_s: number | null;
  decided_count: number;
  avg_wait_ms: number | null;
  max_wait_ms: number | null;
}

export interface ApprovalResolveResponse {
  approval: ApprovalOut;
  run_id: string;
  run_status: string | null;
}

export type ApprovalDecision = 'approved' | 'rejected';
export type ApprovalScope = 'once' | 'session';

export function listApprovals(status = 'pending'): Promise<ApprovalListResponse> {
  return getJson<ApprovalListResponse>(`/approvals?status=${encodeURIComponent(status)}`);
}

export function getApprovalStats(days = 7): Promise<ApprovalStats> {
  return getJson<ApprovalStats>(`/approvals/stats?days=${days}`);
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
