import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getRunEvents, type RunEventsResponse } from '@/api/runs';
import { initialRuntime } from './machine';
import { streamChat } from './stream';
import { useChat } from './store';
import type { RunEvent } from './types';

vi.mock('./stream', () => ({ streamChat: vi.fn<typeof streamChat>() }));
vi.mock('@/api/runs', () => ({ getRunEvents: vi.fn<typeof getRunEvents>() }));

const mockStream = vi.mocked(streamChat);
const mockGetEvents = vi.mocked(getRunEvents);

const evt = (
  seq: number,
  type: string,
  payload: Record<string, unknown> = {},
  runId = 'r1',
): RunEvent => ({
  seq,
  run_id: runId,
  type,
  ts: '2026-11-08T00:00:00Z',
  payload,
});

beforeEach(() => {
  useChat.setState({
    runtime: initialRuntime,
    sending: false,
    lastSeq: 0,
    lastUserText: null,
  });
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
    expect(mockGetEvents).toHaveBeenCalledWith('r1', 2, 200, expect.any(AbortSignal));
    expect(runtime.phase).toBe('completed');
    expect(runtime.messages.at(-1)?.text).toBe('你好');
    expect(runtime.costCents).toBe(2);
    expect(lastSeq).toBe(4);
  });

  it('补拉会翻页直到终态（>200 事件）', async () => {
    const page = Array.from({ length: 200 }, (_, i) => evt(i + 2, 'message.delta', { text: '.' }));
    mockStream.mockImplementation(async (opts) => {
      opts.onEvent(evt(1, 'run.started'));
      throw new Error('network down');
    });
    mockGetEvents
      .mockResolvedValueOnce({ events: page, next_seq: 201, run_status: 'completed' })
      .mockResolvedValueOnce({
        events: [evt(202, 'run.completed', { cost_cents: 7 })],
        next_seq: 202,
        run_status: 'completed',
      });

    await useChat.getState().send('长回答');

    expect(mockGetEvents).toHaveBeenCalledTimes(2);
    expect(mockGetEvents.mock.calls[0]?.[1]).toBe(1);
    expect(mockGetEvents.mock.calls[1]?.[1]).toBe(201);

    const { runtime, lastSeq } = useChat.getState();
    expect(runtime.phase).toBe('completed');
    expect(runtime.costCents).toBe(7);
    expect(lastSeq).toBe(202);
  });

  it('abort 后旧补拉结果不再应用', async () => {
    let resolvePage!: (value: RunEventsResponse) => void;
    const pending = new Promise<RunEventsResponse>((resolve) => {
      resolvePage = resolve;
    });
    mockStream.mockImplementation(async (opts) => {
      opts.onEvent(evt(1, 'run.started'));
      throw new Error('network down');
    });
    mockGetEvents.mockReturnValue(pending);

    const sending = useChat.getState().send('旧问题');
    await vi.waitFor(() => expect(mockGetEvents).toHaveBeenCalled());

    useChat.getState().abort();
    resolvePage({
      events: [evt(2, 'message.completed', { text: 'STALE' }), evt(3, 'run.completed')],
      next_seq: 3,
      run_status: 'completed',
    });
    await sending;

    const { runtime } = useChat.getState();
    expect(runtime.phase).toBe('interrupted');
    expect(runtime.messages.some((m) => m.text === 'STALE')).toBe(false);
  });

  it('旧 run 的事件不会写进新 run', async () => {
    let resolveOld!: (value: RunEventsResponse) => void;
    const oldPending = new Promise<RunEventsResponse>((resolve) => {
      resolveOld = resolve;
    });
    mockStream.mockImplementationOnce(async (opts) => {
      opts.onEvent(evt(1, 'run.started'));
      throw new Error('network down');
    });
    mockGetEvents.mockReturnValue(oldPending);

    const oldSend = useChat.getState().send('旧问题');
    await vi.waitFor(() => expect(mockGetEvents).toHaveBeenCalled());
    useChat.getState().abort();

    mockStream.mockImplementationOnce(async (opts) => {
      opts.onEvent(evt(1, 'run.started', {}, 'r2'));
      opts.onEvent(evt(2, 'message.delta', { text: 'NEW' }, 'r2'));
      opts.onEvent(evt(3, 'run.completed', {}, 'r2'));
    });
    await useChat.getState().send('新问题');

    resolveOld({
      events: [evt(4, 'message.completed', { text: 'OLD' })],
      next_seq: 4,
      run_status: 'completed',
    });
    await oldSend;

    const { runtime } = useChat.getState();
    expect(runtime.runId).toBe('r2');
    expect(runtime.phase).toBe('completed');
    expect(runtime.messages.some((m) => m.text === 'OLD')).toBe(false);
  });

  it('拿不到 runId 时不补拉，直接标失败', async () => {
    mockStream.mockRejectedValue(new Error('HTTP 503'));

    await useChat.getState().send('你好');

    expect(mockGetEvents).not.toHaveBeenCalled();
    const { runtime } = useChat.getState();
    expect(runtime.phase).toBe('failed');
    // 失败后不能留下“正在输入”的光标
    expect(runtime.messages.every((m) => !m.streaming)).toBe(true);
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

describe('失败重试', () => {
  it('移除失败气泡后重发，不重复用户消息，并使用新的幂等键', async () => {
    const clientIds: string[] = [];
    mockStream.mockImplementationOnce(async (opts) => {
      clientIds.push(opts.clientMsgId ?? '');
      throw new Error('HTTP 503');
    });
    await useChat.getState().send('打印机离线');
    expect(useChat.getState().runtime.phase).toBe('failed');

    mockStream.mockImplementationOnce(async (opts) => {
      clientIds.push(opts.clientMsgId ?? '');
      opts.onEvent(evt(1, 'run.started'));
      opts.onEvent(evt(2, 'message.completed', { text: '已恢复' }));
      opts.onEvent(evt(3, 'run.completed', {}));
    });
    await useChat.getState().retry();

    const { runtime, lastUserText } = useChat.getState();
    expect(runtime.phase).toBe('completed');
    expect(
      runtime.messages.filter((m) => m.role === 'user' && m.text === '打印机离线'),
    ).toHaveLength(1);
    expect(lastUserText).toBe('打印机离线');
    expect(clientIds).toHaveLength(2);
    // 原 client_msg_id 会命中幂等回放，拿到的还是失败 run
    expect(clientIds[0]).not.toBe(clientIds[1]);
  });
});
