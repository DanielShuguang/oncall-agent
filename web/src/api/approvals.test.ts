import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  exportApprovalStatsCsv,
  exportApprovalsCsv,
  getApprovalStats,
  listApprovals,
  resolveApproval,
} from './approvals';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('listApprovals', () => {
  it('拼 status/limit/cursor 查询参数，cursor 为空时不带', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listApprovals('pending', 'cur-1', 25);
    await listApprovals('approved');

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/approvals?status=pending&limit=25&cursor=cur-1',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/approvals?status=approved&limit=50');
  });

  it('已办筛选只拼接非空参数（ADR-0054）', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await listApprovals('approved', null, 25, {
      tool: 'create_ticket',
      resolvedBy: 'u_900',
      resolvedFrom: '2026-11-01',
      resolvedTo: '2026-11-02',
    });
    await listApprovals('approved', null, 25, { tool: '' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/approvals?status=approved&limit=25&tool=create_ticket&resolved_by=u_900' +
        '&resolved_from=2026-11-01&resolved_to=2026-11-02',
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/approvals?status=approved&limit=25');
  });
});

describe('getApprovalStats', () => {
  it('旧后端没有 hourly 时补空数组（ADR-0058）', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          days: 7,
          pending_count: 0,
          oldest_pending_age_s: null,
          decided_count: 0,
          avg_wait_ms: null,
          max_wait_ms: null,
          daily: [],
          groups: [],
          groups_truncated: false,
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const stats = await getApprovalStats();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/approvals/stats?days=7');
    expect(stats.hourly).toEqual([]);
  });
});

describe('exportApprovalsCsv', () => {
  it('按状态与筛选拼导出参数，并读取截断响应头（ADR-0056）', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('approval_id\r\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'X-Export-Count': '3',
          'X-Export-Truncated': 'true',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportApprovalsCsv('approved', {
      tool: 'create_ticket',
      resolvedBy: 'u_900',
      resolvedFrom: '2026-11-01',
    });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(
      '/api/approvals/export?status=approved&tool=create_ticket&resolved_by=u_900' +
        '&resolved_from=2026-11-01',
    );
    expect(init?.method).toBeUndefined();
    expect(result.count).toBe(3);
    expect(result.truncated).toBe(true);
    expect(await result.blob.text()).toBe('approval_id\r\n');
  });
});

describe('exportApprovalStatsCsv', () => {
  it('拼窗口与分组参数，并读取统计导出响应头（ADR-0068）', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response('section\r\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv; charset=utf-8',
          'X-Export-Days': '30',
          'X-Export-Group-By': 'approver',
          'X-Export-Groups-Truncated': 'true',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportApprovalStatsCsv(30, 'approver');

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/approvals/stats/export?days=30&group_by=approver',
    );
    expect(result.days).toBe(30);
    expect(result.groupBy).toBe('approver');
    expect(result.groupsTruncated).toBe(true);
    expect(await result.blob.text()).toBe('section\r\n');
  });
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
