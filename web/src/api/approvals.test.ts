import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveApproval } from './approvals';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resolveApproval', () => {
  it('POST 决议并按默认 scope=once', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          approval: { approval_id: 'apr-1', status: 'approved' },
          run_id: 'run-1',
          run_status: 'completed',
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const res = await resolveApproval('apr-1', 'approved');

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/approvals/apr-1/resolve');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ decision: 'approved', scope: 'once' });
    expect(res.run_status).toBe('completed');
  });

  it('approval_id 做 URL 编码', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ approval: {}, run_id: 'r', run_status: 'failed' }), {
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await resolveApproval('a b/c', 'rejected', { reason: '信息不足' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/approvals/a%20b%2Fc/resolve');
  });
});
