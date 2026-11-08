import { afterEach, describe, expect, it, vi } from 'vitest';
import { getRunEvents } from './runs';

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
