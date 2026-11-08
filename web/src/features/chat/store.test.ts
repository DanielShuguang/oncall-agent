import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getRunEvents } from '@/api/runs';
import { initialRuntime } from './machine';
import { streamChat } from './stream';
import { useChat } from './store';
import type { RunEvent } from './types';

vi.mock('./stream', () => ({ streamChat: vi.fn<typeof streamChat>() }));
vi.mock('@/api/runs', () => ({ getRunEvents: vi.fn<typeof getRunEvents>() }));

const mockStream = vi.mocked(streamChat);
const mockGetEvents = vi.mocked(getRunEvents);

const evt = (seq: number, type: string, payload: Record<string, unknown> = {}): RunEvent => ({
  seq,
  run_id: 'r1',
  type,
  ts: '2026-11-08T00:00:00Z',
  payload,
});

beforeEach(() => {
  useChat.setState({ runtime: initialRuntime, sending: false, lastSeq: 0 });
  mockStream.mockReset();
  mockGetEvents.mockReset();
});

describe('断线续传', () => {
  it('流中断后用 after_seq 补拉，并恢复到最后一条事件', async () => {
    mockStream.mockImplementation(async (opts) => {
      opts.onEvent(evt(1, 'run.started', { model: 'mock' }));
      opts.onEvent(evt(2, 'message.delta', { text: '你' }));
      throw new Error('network down');
    });
    mockGetEvents.mockResolvedValue({
      events: [
        evt(3, 'message.completed', { text: '你好' }),
        evt(4, 'run.completed', { cost_cents: 2 }),
      ],
      next_seq: 4,
      run_status: 'completed',
    });

    await useChat.getState().send('打印机离线');

    const { runtime, lastSeq } = useChat.getState();
    expect(mockGetEvents).toHaveBeenCalledWith('r1', 2);
    expect(runtime.phase).toBe('completed');
    expect(runtime.messages.at(-1)?.text).toBe('你好');
    expect(runtime.costCents).toBe(2);
    expect(lastSeq).toBe(4);
  });

  it('拿不到 runId 时不补拉，直接标失败', async () => {
    mockStream.mockRejectedValue(new Error('HTTP 503'));

    await useChat.getState().send('你好');

    expect(mockGetEvents).not.toHaveBeenCalled();
    expect(useChat.getState().runtime.phase).toBe('failed');
  });

  it('补拉失败时保留已收到的部分并标失败', async () => {
    mockStream.mockImplementation(async (opts) => {
      opts.onEvent(evt(1, 'run.started'));
      throw new Error('network down');
    });
    mockGetEvents.mockRejectedValue(new Error('still down'));

    await useChat.getState().send('打印机离线');

    const { runtime } = useChat.getState();
    expect(runtime.phase).toBe('failed');
  });
});
