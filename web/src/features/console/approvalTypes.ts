import type { ApprovalDecision, ApprovalOut, ApprovalScope } from '@/api/approvals';

export type StatsGroup = 'none' | 'tool' | 'approver';

export interface ApprovalResolveState {
  approval: ApprovalOut;
  decision: ApprovalDecision;
  reason: string;
  scope: ApprovalScope;
  submitting: boolean;
  error: string | null;
}
