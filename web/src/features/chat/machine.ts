/**
 * 对话状态机 + 事件归约器。
 *
 * 设计见 docs/07-frontend-design.md：
 * - 状态是显式的 6 个枚举，不用一堆 boolean 拼
 * - 非法转移直接丢弃（线上不能 throw）
 * - 事件是唯一输入，重放历史事件即可重建界面
 */

import type { ApprovalRequest, ChatMessage, Citation, RunEvent, StepItem, ToolCard } from './types';

export type ChatPhase =
  | 'idle'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'interrupted';

export type Trigger = 'SEND' | 'ABORT' | 'RESET' | 'RECONNECTED' | string;

export interface Runtime {
  phase: ChatPhase;
  messages: ChatMessage[];
  steps: StepItem[];
  tools: ToolCard[];
  approval: ApprovalRequest | null;
  runId: string | null;
  error: string | null;
  costCents: number | null;
}

export const TRANSITIONS: Record<ChatPhase, Partial<Record<Trigger, ChatPhase>>> = {
  idle: { SEND: 'running' },
  running: {
    'approval.required': 'awaiting_approval',
    'run.completed': 'completed',
    'run.failed': 'failed',
    ABORT: 'interrupted',
  },
  awaiting_approval: {
    'approval.resolved': 'running',
    'run.completed': 'completed',
    'run.failed': 'failed',
    ABORT: 'interrupted',
    RECONNECTED: 'running',
  },
  completed: { SEND: 'running', RESET: 'idle' },
  failed: { SEND: 'running', RESET: 'idle' },
  interrupted: { SEND: 'running', RECONNECTED: 'running', RESET: 'idle' },
};

export function nextPhase(current: ChatPhase, trigger: Trigger): ChatPhase | null {
  return TRANSITIONS[current]?.[trigger] ?? null;
}

export const initialRuntime: Runtime = {
  phase: 'idle',
  messages: [],
  steps: [],
  tools: [],
  approval: null,
  runId: null,
  error: null,
  costCents: null,
};

let msgSeq = 0;
const uid = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${msgSeq++}`;

/** 当前正在流式输出的助手消息（没有就新建）。 */
function withAssistant(
  messages: ChatMessage[],
  mutate: (m: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const idx = messages.findIndex((m) => m.role === 'assistant' && m.streaming);
  if (idx === -1) {
    const created: ChatMessage = { id: uid('a'), role: 'assistant', text: '', streaming: true };
    return [...messages, mutate(created)];
  }
  const copy = [...messages];
  copy[idx] = mutate(copy[idx]);
  return copy;
}

/**
 * 结束“正在输出”的光标。
 *
 * run.failed / 断连 / 挂起审批时不会再有 message.completed，如果不主动收尾，
 * 界面会一直显示闪烁光标，看起来像还在跑。
 */
export function stopAssistantStreaming(messages: ChatMessage[]): ChatMessage[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'assistant' && messages[i].streaming) {
      const next = [...messages];
      next[i] = { ...messages[i], streaming: false };
      return next;
    }
  }
  return messages;
}

export function runtimeReducer(state: Runtime, event: RunEvent): Runtime {
  const target = nextPhase(state.phase, event.type);
  // 非法转移：丢弃并保留原状态（不 throw，避免整页崩掉）
  const phase = target ?? state.phase;
  const base: Runtime = { ...state, phase };

  switch (event.type) {
    case 'run.started':
      // run_id 是补拉的唯一依据；早前误把 model 当 runId，D4 修掉
      return { ...base, runId: event.run_id };

    case 'step.started':
      return {
        ...base,
        steps: [
          ...state.steps,
          {
            node: String(event.payload.node ?? ''),
            title: String(event.payload.title ?? event.payload.node ?? ''),
            status: 'running',
            seq: event.seq,
          },
        ],
      };

    case 'step.completed': {
      const node = String(event.payload.node ?? '');
      return {
        ...base,
        steps: state.steps.map((s) =>
          s.node === node
            ? {
                ...s,
                status: 'done',
                summary: event.payload.summary ? String(event.payload.summary) : s.summary,
                durationMs: Number(event.payload.duration_ms ?? 0) || undefined,
              }
            : s,
        ),
      };
    }

    case 'tool.call':
      return {
        ...base,
        tools: [
          ...state.tools,
          {
            callId: String(event.payload.call_id ?? ''),
            tool: String(event.payload.tool ?? ''),
            args: (event.payload.args as Record<string, unknown>) ?? {},
            write: Boolean(event.payload.write),
            status: 'running',
          },
        ],
      };

    case 'tool.result':
      return {
        ...base,
        tools: state.tools.map((t) =>
          t.callId === String(event.payload.call_id ?? '')
            ? {
                ...t,
                status: (String(event.payload.status ?? 'ok') as ToolCard['status']) || 'ok',
                result: event.payload.result,
                error: event.payload.error ? String(event.payload.error) : undefined,
                durationMs: Number(event.payload.duration_ms ?? 0) || undefined,
                attempts: Number(event.payload.attempts ?? 0) || undefined,
              }
            : t,
        ),
      };

    case 'approval.required':
      return {
        ...base,
        messages: stopAssistantStreaming(state.messages),
        approval: {
          approvalId: String(event.payload.approval_id ?? ''),
          tool: String(event.payload.tool ?? ''),
          args: (event.payload.args as Record<string, unknown>) ?? {},
          riskLevel: String(event.payload.risk_level ?? 'medium'),
          reason: event.payload.reason ? String(event.payload.reason) : undefined,
          expiresAt: event.payload.expires_at ? String(event.payload.expires_at) : undefined,
        },
      };

    case 'approval.resolved':
      return { ...base, approval: null };

    case 'message.delta':
      return {
        ...base,
        messages: withAssistant(state.messages, (m) => ({
          ...m,
          text: m.text + String(event.payload.text ?? ''),
        })),
      };

    case 'message.completed':
      return {
        ...base,
        messages: withAssistant(state.messages, (m) => ({
          ...m,
          text: String(event.payload.text ?? m.text),
          streaming: false,
          citations: (event.payload.citations as Citation[]) ?? [],
        })),
      };

    case 'run.completed':
      return {
        ...base,
        costCents: Number(event.payload.cost_cents ?? 0) || 0,
        messages: stopAssistantStreaming(state.messages),
      };

    case 'run.failed':
      return {
        ...base,
        messages: stopAssistantStreaming(state.messages),
        error: String(event.payload.message ?? '运行失败'),
      };

    default:
      // 未知事件：忽略而不是崩溃（契约要求）
      return base;
  }
}
