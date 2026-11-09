import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getKbDocument,
  getKbPreview,
  listKbDocuments,
  reindexKb,
  updateKbAccess,
  uploadKbDocument,
  validateKbFile,
} from './kb';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(payload: unknown, status = 200) {
  const fetchMock = vi.fn<typeof fetch>();
  // 每个请求一个全新 Response：复用同一个对象会在第二次 json() 时报 Body is unusable
  fetchMock.mockImplementation(async () => new Response(JSON.stringify(payload), { status }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('kb api', () => {
  it('上传用 multipart，且不手写 Content-Type（浏览器要补 boundary）', async () => {
    const fetchMock = stubFetch({
      document: { id: 'doc_1', title: 'VPN', chunk_count: 2 },
      chunks: [],
    });

    const file = new File(['# VPN'], 'vpn.md', { type: 'text/markdown' });
    await uploadKbDocument(file);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/kb/documents');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(init?.headers).not.toHaveProperty('Content-Type');
  });

  it('上传时把可见范围作为表单字段提交（ADR-0019）', async () => {
    const fetchMock = stubFetch({ document: { id: 'doc_1' }, chunks: [] });

    const file = new File(['# 薪酬'], 'hr.md', { type: 'text/markdown' });
    await uploadKbDocument(file, { visibility: 'roles', roles: ['hr', 'finance'] });
    await uploadKbDocument(file, { visibility: 'public', roles: [] });

    const restricted = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(restricted.get('visibility')).toBe('roles');
    expect(restricted.get('allowed_roles')).toBe('hr,finance');
    const open = fetchMock.mock.calls[1]?.[1]?.body as FormData;
    expect(open.get('visibility')).toBe('public');
    expect(open.get('allowed_roles')).toBe('');
  });

  it('改可见范围走 PATCH，只动 access 不动切片', async () => {
    const fetchMock = stubFetch({ id: 'doc_1', visibility: 'roles', allowed_roles: ['hr'] });

    await updateKbAccess('doc_1', { visibility: 'roles', roles: ['hr'] });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/kb/documents/doc_1/access');
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({
      visibility: 'roles',
      allowed_roles: ['hr'],
    });
  });

  it('详情按 preview 条数请求并转义 id', async () => {
    const fetchMock = stubFetch({ document: { id: 'a/b' }, chunks: [] });

    await getKbDocument('a/b', 50);

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/kb/documents/a%2Fb?preview=50');
  });

  it('列表与重建索引走管理接口', async () => {
    const fetchMock = stubFetch({ documents: [], total: 0, chunk_count: 0 });

    await listKbDocuments();
    await reindexKb();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/kb/documents');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/admin/kb/reindex');
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('POST');
  });

  it('全文预览带 chunk_id 与 ord，且走非管理路由（ADR-0018）', async () => {
    const fetchMock = stubFetch({ document: { id: 'doc_1' }, chunks: [] });

    await getKbPreview('doc_1', { chunkId: 12, ord: 3 });
    await getKbPreview('doc_1');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/kb/documents/doc_1/preview?chunk_id=12&ord=3');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/kb/documents/doc_1/preview');
  });

  it('只在前端挡扩展名，大小交给服务端配置', () => {
    expect(validateKbFile(new File(['x'], 'guide.pdf'))).toBeNull();
    expect(validateKbFile(new File(['x'], 'setup.exe'))).toBe('仅支持 PDF / DOCX / MD / TXT');
    expect(validateKbFile(new File(['x'], 'GUIDE.MD'))).toBeNull();
  });

  it('后端错误消息原样抛给页面', async () => {
    stubFetch({ code: 'PARSE_FAILED', message: '扫描件没有文本层' }, 422);

    await expect(uploadKbDocument(new File(['x'], 'scan.pdf'))).rejects.toThrow('扫描件没有文本层');
  });
});
