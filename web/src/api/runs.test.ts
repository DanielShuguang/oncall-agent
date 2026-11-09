import { afterEach, describe, expect, it, vi } from 'vitest';
import { getAllRunEvents, getRunEvents, listRuns } from './runs';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getRunEvents', () => {
  it('按 after_seq 拼查询参数并解析响应', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ events: [], next_seq: 7, run_status: 'running' }), {
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const res = await getRunEvents('run-1', 6);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs/run-1/events?after_seq=6&limit=200',
      expect.anything(),
    );
    expect(res.next_seq).toBe(7);
    expect(res.run_status).toBe('running');
  });

  it('run_id 做 URL 编码', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ events: [], next_seq: 0, run_status: 'completed' }), {
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getRunEvents('run 1/2', 0, 50);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs/run%201%2F2/events?after_seq=0&limit=50',
      expect.anything(),
    );
  });
});

describe('listRuns', () => {
  it('带 limit / cursor / status 查询', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listRuns({ limit: 20, cursor: 'abc', status: 'failed' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/runs?limit=20&cursor=abc&status=failed');
  });
});

describe('getAllRunEvents', () => {
  it('按 next_seq 翻页直到没有新事件', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            events: [
              { seq: 1, run_id: 'r', type: 'run.started', ts: '', payload: {} },
              { seq: 2, run_id: 'r', type: 'run.completed', ts: '', payload: {} },
            ],
            next_seq: 2,
            run_status: 'completed',
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ events: [], next_seq: 2, run_status: 'completed' }), {
          status: 200,
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const events = await getAllRunEvents('r');

    expect(events.map((event) => event.seq)).toEqual([1, 2]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
