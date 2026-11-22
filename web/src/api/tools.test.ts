import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  exampleArgs,
  exportToolHistoryCsv,
  getToolHistory,
  rollbackToolChange,
  testTool,
  updateTool,
} from './tools';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn<typeof fetch>();
  fetchMock.mockImplementation(async () => new Response(JSON.stringify(payload), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('tools api', () => {
  it('试调用 POST 到工具 test 路径并带回参数', async () => {
    const fetchMock = stubFetch({
      tool: 'query_cmdb',
      decision: 'executed',
      status: 'ok',
      result: { asset_id: 'PC-1' },
      error: null,
      error_kind: null,
      duration_ms: 3,
      attempts: 1,
    });

    const res = await testTool('query_cmdb', { owner_id: 'u_102' });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/tools/query_cmdb/test');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ args: { owner_id: 'u_102' } });
    expect(res.result).toEqual({ asset_id: 'PC-1' });
  });

  it('启停用 PATCH，enabled=null 表示恢复默认', async () => {
    const fetchMock = stubFetch({ name: 'query_cmdb', enabled: true, overridden: false });

    await updateTool('query_cmdb', { enabled: null });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/tools/query_cmdb');
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: null });
  });

  it('回滚 POST 到历史记录路径', async () => {
    const fetchMock = stubFetch({ name: 'query_cmdb', enabled: true, overridden: false });

    await rollbackToolChange('query_cmdb', 7);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/tools/query_cmdb/history/7/rollback');
    expect(init?.method).toBe('POST');
  });
  it('按 schema 生成可编辑的示例参数', () => {
    const args = exampleArgs({
      properties: {
        owner_id: { type: 'string' },
        priority: { type: 'string', enum: ['P0', 'P1'] },
        count: { type: 'integer' },
        dry_run: { type: 'boolean' },
        tags: { type: 'array' },
      },
    });

    expect(args).toEqual({
      owner_id: 'u_102',
      priority: 'P0',
      count: 0,
      dry_run: false,
      tags: [],
    });
  });
});

describe('exportToolHistoryCsv', () => {
  it('导出带已应用日期范围并读取条数头', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response('csv', {
          status: 200,
          headers: { 'X-Export-Count': '2', 'X-Export-Truncated': 'false' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportToolHistoryCsv('query_cmdb', {
      changedFrom: '2026-01-01',
      changedTo: '2026-01-31',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history/export?changed_from=2026-01-01&changed_to=2026-01-31',
    );
    expect(result.count).toBe(2);
    expect(result.truncated).toBe(false);
  });

  it('导出带变更人与来源过滤', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(async () => new Response('csv', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await exportToolHistoryCsv('query_cmdb', {
      changedBy: 'admin_1',
      source: 'matrix',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history/export?changed_by=admin_1&source=matrix',
    );
  });

  it('没有日期时只请求导出路径', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(async () => new Response('csv', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await exportToolHistoryCsv('query_cmdb');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/tools/query_cmdb/history/export');
  });

  it('最早在前时导出也带 order=earliest', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(async () => new Response('csv', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await exportToolHistoryCsv('query_cmdb', { order: 'earliest' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history/export?order=earliest',
    );
  });
});

describe('getToolHistory', () => {
  it('默认只带 limit', async () => {
    const fetchMock = stubFetch({ items: [] });

    await getToolHistory('query_cmdb');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/tools/query_cmdb/history?limit=20');
  });

  it('日期范围同时存在时追加 changed_from/changed_to', async () => {
    const fetchMock = stubFetch({ items: [] });

    await getToolHistory('query_cmdb', 30, {
      changedFrom: '2026-01-01',
      changedTo: '2026-01-31',
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history?limit=30&changed_from=2026-01-01&changed_to=2026-01-31',
    );
  });

  it('追加变更人与来源过滤', async () => {
    const fetchMock = stubFetch({ items: [] });

    await getToolHistory('query_cmdb', 20, { changedBy: 'admin_1', source: 'matrix' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history?limit=20&changed_by=admin_1&source=matrix',
    );
  });

  it('翻页时追加 cursor', async () => {
    const fetchMock = stubFetch({ items: [], total: null, next_cursor: null });

    await getToolHistory('query_cmdb', 20, {}, 'next-page');

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history?limit=20&cursor=next-page',
    );
  });

  it('最早在前时追加 order=earliest', async () => {
    const fetchMock = stubFetch({ items: [] });

    await getToolHistory('query_cmdb', 20, { order: 'earliest' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/admin/tools/query_cmdb/history?limit=20&order=earliest',
    );
  });
});
