/**
 * 事件类型与前端视图模型。
 *
 * 与服务端 app/schemas/event.py 一一对应；正式项目里应由
 * `pnpm gen:api` 生成 src/api/generated.ts 后从这里 re-export。
 */

export type EventType =
  | 'run.started'
  | 'step.started'
  | 'step.completed'
  | 'tool.call'
  | 'tool.result'
  | 'approval.required'
  | 'approval.resolved'
  | 'message.delta'
  | 'message.completed'
  | 'run.completed'
  | 'run.failed'
  | 'heartbeat';

export interface RunEvent {
  seq: number;
  run_id: string;
  type: EventType | string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface Citation {
  chunk_id: number;
  document_id: string;
  ord: number;
  title: string;
  heading?: string | null;
  snippet: string;
  page?: number | null;
}

export interface ToolCard {
  callId: string;
  tool: string;
  args: Record<string, unknown>;
  write: boolean;
  status: 'running' | 'ok' | 'error' | 'timeout' | 'denied' | 'requires_approval';
  result?: unknown;
  error?: string;
  durationMs?: number;
  attempts?: number;
}

export interface StepItem {
  node: string;
  title: string;
  status: 'running' | 'done';
  /** 对应 step.started 的 seq，用于 React key（节点可能重规划重复出现） */
  seq?: number;
  summary?: string;
  durationMs?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  streaming?: boolean;
  citations?: Citation[];
  /** 历史回答的运行过程（ADR-0035）；只读，不回放 message.delta */
  timeline?: TimelineItem[];
  /** false 表示事件已过保留期，不能把「不可用」显示成「没有过程」 */
  timelineAvailable?: boolean;
  timelineTruncated?: boolean;
}

export interface ToolTimelineItem {
  kind: 'tool';
  seq: number;
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  write: boolean;
  status: string;
  result?: unknown;
  error?: string;
  error_kind?: string;
  duration_ms?: number;
  attempts?: number;
}

export interface ApprovalTimelineItem {
  kind: 'approval';
  seq: number;
  approval_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk_level: string;
  reason?: string;
  expires_at?: string;
  status: string;
  resolved_at?: string;
  decision_reason?: string;
}

export type TimelineItem = ToolTimelineItem | ApprovalTimelineItem;

export interface ApprovalRequest {
  approvalId: string;
  tool: string;
  args: Record<string, unknown>;
  riskLevel: string;
  reason?: string;
  expiresAt?: string;
}
