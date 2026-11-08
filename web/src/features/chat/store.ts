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
 */

import { create } from 'zustand';
import { getRunEvents, type RunEventsResponse } from '@/api/runs';
import { initialRuntime, runtimeReducer, stopAssistantStreaming, type Runtime } from './machine';
import { streamChat } from './stream';
import type { RunEvent } from './types';

const SESSION_ID = `sess_${Math.random().toString(36).slice(2, 10)}`;
const RESUME_WINDOW_MS = 120_000;
const RESUME_INTERVAL_MS = 1000;
const RESUME_PAGE_SIZE = 200;

let abortRef: AbortController | null = null;

interface ChatStore {
  runtime: Runtime;
  sending: boolean;
  lastSeq: number;
  send: (text: string) => Promise<void>;
  abort: () => void;
  reset: () => void;
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
    sending: false,
    lastSeq: 0,

    send: async (text: string) => {
      if (get().sending || !text.trim()) return;
      const gen = ++generation;

      const prev = get().runtime;
      set({
        sending: true,
        lastSeq: 0,
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
      const clientMsgId = `cmsg_${Date.now()}`;

      try {
        await streamChat({
          message: text,
          sessionId: SESSION_ID,
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
      set({ runtime: initialRuntime, lastSeq: 0, sending: false });
    },
  };
});
