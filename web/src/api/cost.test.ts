import { afterEach, describe, expect, it, vi } from 'vitest';
import { getCostSummary } from './cost';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getCostSummary', () => {
  it('拼 from/to/group_by 并解析聚合结果', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          total_cents: 7,
          calls: 2,
          items: [{ key: 'day', calls: 2, token_in: 1, token_out: 1, cost_cents: 7 }],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const res = await getCostSummary({
      from: '2026-11-01',
      to: '2026-11-09',
      groupBy: 'day',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/cost/summary?from=2026-11-01&to=2026-11-09&group_by=day',
    );
    expect(res.total_cents).toBe(7);
    expect(res.items[0]?.cost_cents).toBe(7);
  });
});
