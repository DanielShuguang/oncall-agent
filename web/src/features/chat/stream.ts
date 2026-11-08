/**
 * SSE 客户端。
 *
 * 用 fetch + ReadableStream 而不是 EventSource：需要 POST 与鉴权头。
 * 分帧规则见 docs/03-api-contract.md：以空行分隔，data 可能多行。
 */

import type { RunEvent } from './types';

export interface StreamOptions {
  message: string;
  sessionId: string;
  clientMsgId?: string;
  signal?: AbortSignal;
  onEvent: (event: RunEvent) => void;
  onError?: (error: unknown) => void;
}

interface Frame {
  id?: string;
  event?: string;
  data?: string;
}

export function parseFrame(raw: string): Frame | null {
  const frame: Frame = {};
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue; // 注释/心跳
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    const field = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).replace(/^ /, '');
    if (field === 'id') frame.id = value;
    else if (field === 'event') frame.event = value;
    else if (field === 'data') frame.data = frame.data ? `${frame.data}\n${value}` : value;
  }
  return frame.event || frame.data ? frame : null;
}

export async function streamChat(opts: StreamOptions): Promise<void> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      session_id: opts.sessionId,
      client_msg_id: opts.clientMsgId,
      message: opts.message,
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`建流失败: HTTP ${res.status}`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;

      let sep = buffer.indexOf('\n\n');
      while (sep >= 0) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        sep = buffer.indexOf('\n\n');

        const frame = parseFrame(raw);
        if (!frame?.event || !frame.data) continue;

        try {
          const parsed = JSON.parse(frame.data) as RunEvent;
          opts.onEvent(parsed);
        } catch {
          // 坏帧跳过，不影响后续
        }
      }
    }
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return; // 用户主动中断
    opts.onError?.(err);
    throw err;
  }
}
