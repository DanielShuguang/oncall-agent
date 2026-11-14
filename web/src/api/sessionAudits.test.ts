import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  exportSessionRestoreAuditsCsv,
  getSessionRestoreAuditStats,
  listSessionRestoreAudits,
} from './sessionAudits';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listSessionRestoreAudits', () => {
  it('拼 user_id/session_id/cursor/limit，空过滤不拼接', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listSessionRestoreAudits({ userId: 'u_102', sessionId: 'sess a' }, 'cur-1', 20);
    await listSessionRestoreAudits();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores?limit=20&cursor=cur-1&user_id=u_102&session_id=sess+a',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/admin/session-restores?limit=20');
  });
});

describe('getSessionRestoreAuditStats', () => {
  it('按天数请求统计', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          days: 7,
          since: '2026-11-07T00:00:00Z',
          until: '2026-11-14T00:00:00Z',
          restores: 2,
          users: 2,
          sessions: 3,
          daily: [{ day: '2026-11-14', restores: 2, sessions: 3 }],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const stats = await getSessionRestoreAuditStats(7);

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/session-restores/stats?days=7');
    expect(stats.sessions).toBe(3);
  });
});

describe('exportSessionRestoreAuditsCsv', () => {
  it('按当前过滤导出并读取截断响应头', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('audit_id\r\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'X-Export-Count': '4',
          'X-Export-Truncated': 'true',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportSessionRestoreAuditsCsv({ sessionId: 'sess_a' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores/export?session_id=sess_a',
    );
    expect(result.count).toBe(4);
    expect(result.truncated).toBe(true);
    expect(await result.blob.text()).toBe('audit_id\r\n');
  });

  it('没有过滤时不带查询串', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('audit_id\r\n', {
        status: 200,
        headers: { 'X-Export-Count': '0', 'X-Export-Truncated': 'false' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await exportSessionRestoreAuditsCsv();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/session-restores/export');
  });
});
