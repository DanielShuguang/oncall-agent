/**
 * 对话 store（Zustand）。
 *
 * 只用它管"当前这一轮"的运行态；历史会话由后端 /runs 提供。
 */

import { create } from 'zustand';
import { initialRuntime, runtimeReducer, type Runtime } from './machine';
import { streamChat } from './stream';
import type { RunEvent } from './types';

const SESSION_ID = `sess_${Math.random().toString(36).slice(2, 10)}`;

let abortRef: AbortController | null = null;

interface ChatStore {
  runtime: Runtime;
  sending: boolean;
  lastSeq: number;
  send: (text: string) => Promise<void>;
  abort: () => void;
  reset: () => void;
}

export const useChat = create<ChatStore>((set, get) => ({
  runtime: initialRuntime,
  sending: false,
  lastSeq: 0,

  send: async (text: string) => {
    if (get().sending || !text.trim()) return;

    const prev = get().runtime;
    set({
      sending: true,
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

    abortRef = new AbortController();
    const clientMsgId = `cmsg_${Date.now()}`;

    try {
      await streamChat({
        message: text,
        sessionId: SESSION_ID,
        clientMsgId,
        signal: abortRef.signal,
        onEvent: (event: RunEvent) => {
          set((s) => ({
            runtime: runtimeReducer(s.runtime, event),
            lastSeq: Math.max(s.lastSeq, event.seq),
          }));
        },
      });
    } catch (err) {
      set((s) => ({
        runtime: { ...s.runtime, phase: 'failed', error: (err as Error).message },
      }));
    } finally {
      abortRef = null;
      set({ sending: false });
    }
  },

  abort: () => {
    abortRef?.abort();
    set((s) => ({ runtime: { ...s.runtime, phase: 'interrupted' }, sending: false }));
  },

  reset: () => set({ runtime: initialRuntime, lastSeq: 0 }),
}));
