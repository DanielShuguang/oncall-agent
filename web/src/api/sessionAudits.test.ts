import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  exportSessionRestoreAuditsCsv,
  exportSessionRestoreAuditStatsCsv,
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
    await listSessionRestoreAudits({
      restoredFrom: '2026-11-01',
      restoredTo: '2026-11-02',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores?limit=20&cursor=cur-1&user_id=u_102&session_id=sess+a',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/admin/session-restores?limit=20');
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      '/api/admin/session-restores?limit=20&restored_from=2026-11-01&restored_to=2026-11-02',
    );
  });
});

describe('getSessionRestoreAuditStats', () => {
  it('按天数请求统计', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
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

    await getSessionRestoreAuditStats(30, { userId: 'u_102', sessionId: 'sess_a' });
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/admin/session-restores/stats?days=30&user_id=u_102&session_id=sess_a',
    );

    await getSessionRestoreAuditStats(null, {
      restoredFrom: '2026-11-01',
      restoredTo: '2026-11-02',
    });
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      '/api/admin/session-restores/stats?restored_from=2026-11-01&restored_to=2026-11-02',
    );
  });
});

describe('exportSessionRestoreAuditStatsCsv', () => {
  it('按当前窗口/过滤导出统计并读取汇总响应头', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('section,key,day,value\r\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'X-Export-Days': '7',
          'X-Export-Restores': '3',
          'X-Export-Users': '2',
          'X-Export-Sessions': '5',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportSessionRestoreAuditStatsCsv(7, { userId: 'u_102' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores/stats/export?days=7&user_id=u_102',
    );
    expect(result).toMatchObject({ days: 7, restores: 3, users: 2, sessions: 5 });
  });

  it('日期范围决定窗口时不发送 days', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('section,key,day,value\r\n', {
        status: 200,
        headers: { 'X-Export-Days': '2' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await exportSessionRestoreAuditStatsCsv(30, {
      restoredFrom: '2026-11-01',
      restoredTo: '2026-11-02',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores/stats/export?restored_from=2026-11-01&restored_to=2026-11-02',
    );
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

    const result = await exportSessionRestoreAuditsCsv({
      sessionId: 'sess_a',
      restoredFrom: '2026-11-01',
      restoredTo: '2026-11-02',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/session-restores/export?session_id=sess_a&restored_from=2026-11-01&restored_to=2026-11-02',
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
