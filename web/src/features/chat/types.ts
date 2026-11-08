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
  summary?: string;
  durationMs?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  streaming?: boolean;
  citations?: Citation[];
}

export interface ApprovalRequest {
  approvalId: string;
  tool: string;
  args: Record<string, unknown>;
  riskLevel: string;
  reason?: string;
  expiresAt?: string;
}
