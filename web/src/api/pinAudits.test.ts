import { afterEach, describe, expect, it, vi } from 'vitest';
import { exportSessionPinAuditsCsv, listSessionPinAudits } from './pinAudits';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listSessionPinAudits', () => {
  it('拼过滤/游标/limit，空过滤不拼接', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listSessionPinAudits({ userId: 'u_102', sessionId: 'sess a', action: 'unpin' }, 'cur-1');
    await listSessionPinAudits();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-pins?limit=20&cursor=cur-1&user_id=u_102&session_id=sess+a&action=unpin',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/admin/session-pins?limit=20');
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
