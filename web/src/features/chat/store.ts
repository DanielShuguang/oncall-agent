/**
 * 对话 store（Zustand）。
 *
 * 只用它管"当前这一轮"的运行态；历史会话由后端 /runs 提供。
 *
 * 断线续传（W1 D4）：流断了不要直接判失败 —— 拿 runId + lastSeq 去
 * `GET /runs/{id}/events?after_seq=` 补拉，run 仍在 running 就轮询到终态。
 * 补拉是幂等的：只应用 seq 更大的事件，重复帧不会重复渲染。
 */

import { create } from 'zustand';
import { getRunEvents } from '@/api/runs';
import { initialRuntime, runtimeReducer, type Runtime } from './machine';
import { streamChat } from './stream';
import type { RunEvent } from './types';

const SESSION_ID = `sess_${Math.random().toString(36).slice(2, 10)}`;
const RESUME_WINDOW_MS = 120_000;
const RESUME_INTERVAL_MS = 1000;

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
  const applyEvent = (event: RunEvent) => {
    set((s) => ({
      runtime: runtimeReducer(s.runtime, event),
      lastSeq: Math.max(s.lastSeq, event.seq),
    }));
  };

  /** 返回 true 表示已通过补拉恢复到终态/等待审批，调用方不要再置 failed。 */
  const catchUp = async (runId: string, signal: AbortSignal): Promise<boolean> => {
    const deadline = Date.now() + RESUME_WINDOW_MS;
    while (Date.now() < deadline) {
      if (signal.aborted) return true;
      try {
        // 轮询必须串行：下一次 after_seq 依赖这次已经应用的事件
        // oxlint-disable-next-line no-await-in-loop
        const res = await getRunEvents(runId, get().lastSeq);
        for (const event of res.events) applyEvent(event);

        if (res.run_status === 'interrupted') {
          set((s) => ({ runtime: { ...s.runtime, phase: 'interrupted' } }));
          return true;
        }
        if (res.run_status !== 'running') return true;
      } catch {
        return false;
      }
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
          onEvent: applyEvent,
        });
      } catch (err) {
        if ((err as Error)?.name === 'AbortError') return;

        const runId = get().runtime.runId;
        const recovered = runId ? await catchUp(runId, controller.signal) : false;
        if (!recovered) {
          set((s) => ({
            runtime: { ...s.runtime, phase: 'failed', error: (err as Error).message },
          }));
        }
      } finally {
        if (abortRef === controller) abortRef = null;
        set({ sending: false });
      }
    },

    abort: () => {
      abortRef?.abort();
      set((s) => ({ runtime: { ...s.runtime, phase: 'interrupted' }, sending: false }));
    },

    reset: () => set({ runtime: initialRuntime, lastSeq: 0 }),
  };
});
