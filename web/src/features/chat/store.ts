/**
 * 对话 store（Zustand）。
 *
 * 只用它管"当前这一轮"的运行态；历史会话由后端 /runs 提供。
 *
 * 断线续传（W1 D4）：流断了不要直接判失败 —— 拿 runId + lastSeq 去
 * `GET /runs/{id}/events?after_seq=` 补拉，run 仍在 running 就轮询到终态。
 * 补拉是幂等的：只应用 seq 更大的事件，重复帧不会重复渲染。
 *
 * 每次 send 有一个 generation token：abort/新消息会推进 generation，
 * 旧的补拉或旧流回来的事件一律丢弃，避免把上一个 run 的事件写进新 run。
 *
 * 会话 ID 是**多轮上下文的作用域**（服务端按 user + session 取最近几轮，ADR-0020）：
 * 清空对话必须换一个新 ID，否则"新会话"的第一句话会带着上一段的上下文。
 */

import { create } from 'zustand';
import { resolveApproval, type ApprovalDecision } from '@/api/approvals';
import { getRunEvents, type RunEventsResponse } from '@/api/runs';
import { initialRuntime, runtimeReducer, stopAssistantStreaming, type Runtime } from './machine';
import { streamChat } from './stream';
import type { ChatMessage, RunEvent } from './types';

const newSessionId = () => `sess_${Math.random().toString(36).slice(2, 10)}`;
let sessionId = newSessionId();
const RESUME_WINDOW_MS = 120_000;
const RESUME_INTERVAL_MS = 1000;
const RESUME_PAGE_SIZE = 200;

let abortRef: AbortController | null = null;

interface ChatStore {
  runtime: Runtime;
  /** 当前多轮作用域；「继续对话」会切到历史会话，普通发送沿用 */
  sessionId: string;
  sending: boolean;
  lastSeq: number;
  /** 最近一次发送的文本，失败后「重试」复用；不额外发 run 上下文 */
  lastUserText: string | null;
  send: (text: string) => Promise<void>;
  retry: () => Promise<void>;
  resolve: (decision: ApprovalDecision) => Promise<void>;
  abort: () => void;
  reset: () => void;
  /** 切到历史会话：清掉当前运行态，用只读 transcript 填消息（ADR-0030） */
  switchSession: (nextSessionId: string, messages: ChatMessage[]) => void;
}

export const useChat = create<ChatStore>((set, get) => {
  // 只增不减；代替"用 sending 布尔值防并发"的旧写法
  let generation = 0;

  const applyEvent = (event: RunEvent, gen: number) => {
    if (gen !== generation) return;
    const currentRunId = get().runtime.runId;
    if (currentRunId && event.run_id !== currentRunId) return;
    set((s) => ({
      runtime: runtimeReducer(s.runtime, event),
      lastSeq: Math.max(s.lastSeq, event.seq),
    }));
  };

  /** 返回 true 表示已恢复到终态/等待审批，调用方不要再置 failed。 */
  const catchUp = async (runId: string, signal: AbortSignal, gen: number): Promise<boolean> => {
    const deadline = Date.now() + RESUME_WINDOW_MS;
    while (Date.now() < deadline) {
      if (signal.aborted || gen !== generation) return true;

      let res: RunEventsResponse;
      try {
        // 轮询必须串行：下一次 after_seq 依赖这次已经应用的事件
        // oxlint-disable-next-line no-await-in-loop
        res = await getRunEvents(runId, get().lastSeq, RESUME_PAGE_SIZE, signal);
      } catch {
        return false;
      }

      // fetch 期间可能被 abort，或用户已经发了新消息
      if (signal.aborted || gen !== generation) return true;

      // 引用文档被收权后事件整场不回放（ADR-0022）：这是确定结论，不是"还没好"，
      // 继续轮询只会让转圈停不下来。与后端 200 + 空数组的语义配套。
      if (res.content_redacted) {
        set((s) => ({
          runtime: {
            ...s.runtime,
            phase: 'failed',
            error: '该回答引用的文档已不可见，内容不再展示',
            messages: stopAssistantStreaming(s.runtime.messages),
          },
        }));
        return true;
      }

      for (const event of res.events) applyEvent(event, gen);

      // 满页说明可能还有下一页：即使 run_status 已是终态也要继续翻，
      // 否则 >200 事件的 run 会丢掉最后的 message.completed / run.completed
      if (res.events.length === RESUME_PAGE_SIZE) continue;

      if (res.run_status === 'interrupted') {
        set((s) => ({
          runtime: {
            ...s.runtime,
            phase: 'interrupted',
            messages: stopAssistantStreaming(s.runtime.messages),
          },
        }));
        return true;
      }
      if (res.run_status !== 'running') return true;

      // oxlint-disable-next-line no-await-in-loop -- 固定间隔轮询，不能并发
      await new Promise((resolve) => setTimeout(resolve, RESUME_INTERVAL_MS));
    }
    return false;
  };

  return {
    runtime: initialRuntime,
    sessionId,
    sending: false,
    lastSeq: 0,
    lastUserText: null,

    send: async (text: string) => {
      if (get().sending || !text.trim()) return;
      const gen = ++generation;

      const prev = get().runtime;
      set({
        sending: true,
        lastSeq: 0,
        lastUserText: text,
        runtime: {
          ...initialRuntime,
          phase: 'running',
          // 保留历史消息，但清空本轮步骤与工具
          messages: [
            ...prev.messages,
            { id: `u_${Date.now()}`, role: 'user', text },
            { id: `a_${Date.now()}`, role: 'assistant', text: '', streaming: true },
          ],
        },
      });

      const controller = new AbortController();
      abortRef = controller;
      const clientMsgId = `cmsg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

      try {
        await streamChat({
          message: text,
          sessionId,
          clientMsgId,
          signal: controller.signal,
          onEvent: (event) => applyEvent(event, gen),
        });
      } catch (err) {
        if ((err as Error)?.name === 'AbortError') return;

        const runId = get().runtime.runId;
        const recovered = runId ? await catchUp(runId, controller.signal, gen) : false;
        if (!recovered && gen === generation) {
          set((s) => ({
            runtime: {
              ...s.runtime,
              phase: 'failed',
              error: (err as Error).message,
              messages: stopAssistantStreaming(s.runtime.messages),
            },
          }));
        }
      } finally {
        if (abortRef === controller) abortRef = null;
        // abort/新消息已经推进 generation，旧 send 不要覆盖新的 sending
        if (gen === generation) set({ sending: false });
      }
    },

    /**
     * 失败重试：去掉上一轮失败的用户/助手气泡后重新发送，避免对话里出现两条同样的问题。
     * 每次都生成新的 client_msg_id —— 用原 id 会命中幂等回放，拿回来的还是那条失败 run。
     */
    retry: async () => {
      const text = get().lastUserText;
      if (!text || get().sending) return;
      const messages = get().runtime.messages;
      let end = messages.length;
      while (end > 0 && messages[end - 1]?.role === 'assistant') end -= 1;
      if (end > 0 && messages[end - 1]?.role === 'user' && messages[end - 1]?.text === text) {
        end -= 1;
      }
      set({
        runtime: { ...initialRuntime, messages: messages.slice(0, end) },
        lastSeq: 0,
      });
      await get().send(text);
    },

    /**
     * 审批决议：先提交，再用与断线恢复相同的补拉路径把后续事件写进 UI。
     * 不在这里假设"批准后一定成功"—— run 可能因写工具失败而 failed。
     */
    resolve: async (decision: ApprovalDecision) => {
      const { runtime, sending } = get();
      const approval = runtime.approval;
      const runId = runtime.runId;
      if (!approval || !runId || sending) return;

      const gen = generation;
      const controller = new AbortController();
      abortRef = controller;
      set({ sending: true });

      try {
        await resolveApproval(approval.approvalId, decision);
        const recovered = await catchUp(runId, controller.signal, gen);
        if (!recovered && gen === generation) {
          set((s) => ({
            runtime: {
              ...s.runtime,
              phase: 'failed',
              error: '审批已提交，但拉取执行结果超时，请刷新页面重试',
              messages: stopAssistantStreaming(s.runtime.messages),
            },
          }));
        }
      } catch (err) {
        if (gen === generation) {
          set((s) => ({
            runtime: { ...s.runtime, error: (err as Error).message },
          }));
        }
      } finally {
        if (abortRef === controller) abortRef = null;
        if (gen === generation) set({ sending: false });
      }
    },

    abort: () => {
      generation += 1;
      abortRef?.abort();
      abortRef = null;
      set((s) => ({
        runtime: {
          ...s.runtime,
          phase: 'interrupted',
          messages: stopAssistantStreaming(s.runtime.messages),
        },
        sending: false,
      }));
    },

    reset: () => {
      generation += 1;
      abortRef?.abort();
      abortRef = null;
      // 换会话 ID：服务端按它取历史，"清空对话"之后不能再续上一段的上下文
      sessionId = newSessionId();
      set({
        runtime: initialRuntime,
        sessionId,
        lastSeq: 0,
        sending: false,
        lastUserText: null,
      });
    },

    switchSession: (nextSessionId, messages) => {
      if (!nextSessionId || nextSessionId === sessionId) return;
      generation += 1;
      abortRef?.abort();
      abortRef = null;
      sessionId = nextSessionId;
      set({
        runtime: { ...initialRuntime, messages },
        sessionId: nextSessionId,
        lastSeq: 0,
        sending: false,
        lastUserText: null,
      });
    },
  };
});
