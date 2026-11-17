import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  exportSessionPinAuditsCsv,
  getSessionPinAuditStats,
  listSessionPinAudits,
} from './pinAudits';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listSessionPinAudits', () => {
  it('拼过滤/游标/limit，空过滤不拼接', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ items: [], next_cursor: null, total: 7 }), {
          status: 200,
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const first = await listSessionPinAudits(
      {
        userId: 'u_102',
        sessionId: 'sess a',
        action: 'unpin',
        createdFrom: '2026-11-01',
        createdTo: '2026-11-16',
      },
      'cur-1',
    );
    await listSessionPinAudits();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-pins?limit=20&cursor=cur-1&user_id=u_102&session_id=sess+a&action=unpin&created_from=2026-11-01&created_to=2026-11-16',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/admin/session-pins?limit=20');
    expect(first.total).toBe(7);
  });
});

describe('getSessionPinAuditStats', () => {
  it('按天数请求全局统计并解析日趋势', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            days: 7,
            since: '2026-11-09T00:00:00Z',
            until: '2026-11-16T00:00:00Z',
            pins: 3,
            unpins: 1,
            users: 2,
            sessions: 2,
            daily: [{ day: '2026-11-16', pins: 3, unpins: 1 }],
          }),
          { status: 200 },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const stats = await getSessionPinAuditStats(7);

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/session-pins/stats?days=7');
    expect(stats.pins).toBe(3);
    expect(stats.daily).toHaveLength(1);
    expect(stats.daily[0]?.unpins).toBe(1);
  });
});

describe('getSessionPinAuditStats filters', () => {
  it('带用户/会话/动作过滤时拼接参数，仍保留 days', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            days: 30,
            since: '2026-10-18T00:00:00Z',
            until: '2026-11-17T00:00:00Z',
            pins: 1,
            unpins: 0,
            users: 1,
            sessions: 1,
            daily: [],
          }),
          { status: 200 },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getSessionPinAuditStats(30, { userId: 'u_102', sessionId: 'sess a', action: 'pin' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-pins/stats?user_id=u_102&session_id=sess+a&action=pin&days=30',
    );
  });

  it('日期范围优先，不再发送 days', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            days: 2,
            since: '2026-11-01T00:00:00Z',
            until: '2026-11-02T23:59:59.999999Z',
            pins: 0,
            unpins: 0,
            users: 0,
            sessions: 0,
            daily: [],
          }),
          { status: 200 },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    await getSessionPinAuditStats(30, {
      createdFrom: '2026-11-01',
      createdTo: '2026-11-02',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-pins/stats?created_from=2026-11-01&created_to=2026-11-02',
    );
  });
});
describe('exportSessionPinAuditsCsv', () => {
  it('按当前过滤导出并读取截断响应头', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(new Blob(['csv']), {
          status: 200,
          headers: { 'X-Export-Count': '2', 'X-Export-Truncated': 'true' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportSessionPinAuditsCsv({ action: 'pin' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/session-pins/export?action=pin');
    expect(result.count).toBe(2);
    expect(result.truncated).toBe(true);
  });

  it('按日期范围导出', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(new Blob(['csv']), {
          status: 200,
          headers: { 'X-Export-Count': '1', 'X-Export-Truncated': 'false' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await exportSessionPinAuditsCsv({
      createdFrom: '2026-11-01',
      createdTo: '2026-11-16',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-pins/export?created_from=2026-11-01&created_to=2026-11-16',
    );
  });

  it('无过滤导出不带查询串', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(new Blob(['csv']), {
          status: 200,
          headers: { 'X-Export-Count': '0', 'X-Export-Truncated': 'false' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await exportSessionPinAuditsCsv();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/session-pins/export');
  });
});
