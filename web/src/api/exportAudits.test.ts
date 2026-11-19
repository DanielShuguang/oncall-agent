import { afterEach, describe, expect, it, vi } from 'vitest';
import { exportExportAuditsCsv, listExportAudits } from './exportAudits';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listExportAudits', () => {
  it('拼过滤/游标/limit', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ items: [], next_cursor: 'next', total: 2 }), {
          status: 200,
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const page = await listExportAudits(
      {
        userId: 'u_102',
        resource: 'session_pins',
        createdFrom: '2026-11-01',
        createdTo: '2026-11-02',
      },
      'cur-1',
      50,
    );

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/export-audits?limit=50&cursor=cur-1&user_id=u_102&resource=session_pins&created_from=2026-11-01&created_to=2026-11-02',
    );
    expect(page.total).toBe(2);
    expect(page.next_cursor).toBe('next');
  });

  it('空过滤只带 limit', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ items: [], next_cursor: null, total: 0 }), {
          status: 200,
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listExportAudits();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/export-audits?limit=20');
  });
});

describe('exportExportAuditsCsv', () => {
  it('拼过滤参数并读取响应头', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response('created_at\n', {
          status: 200,
          headers: {
            'Content-Type': 'text/csv',
            'X-Export-Count': '3',
            'X-Export-Truncated': 'true',
          },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportExportAuditsCsv({
      resource: 'export_audits',
      createdFrom: '2026-11-01',
      createdTo: '2026-11-02',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/export-audits/export?resource=export_audits&created_from=2026-11-01&created_to=2026-11-02',
    );
    expect(result.count).toBe(3);
    expect(result.truncated).toBe(true);
  });
});
