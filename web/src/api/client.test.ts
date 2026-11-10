import { afterEach, describe, expect, it, vi } from 'vitest';
import { del, getJson, getToken, setToken } from './client';

function stubStorage() {
  const data = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  });
}

function stubFetch(status = 200) {
  const fetchMock = vi.fn<typeof fetch>();
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function headersOf(call: RequestInit | undefined): Record<string, string> {
  return (call?.headers ?? {}) as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token', () => {
  it('没有 token 时不带 Authorization', async () => {
    stubStorage();
    const fetchMock = stubFetch();

    await getJson('/health');

    expect(headersOf(fetchMock.mock.calls[0]?.[1])).not.toHaveProperty('Authorization');
  });

  it('保存后请求自动带 Bearer', async () => {
    stubStorage();
    const fetchMock = stubFetch();

    setToken('abc.def.ghi');
    expect(getToken()).toBe('abc.def.ghi');
    await getJson('/health');

    expect(headersOf(fetchMock.mock.calls[0]?.[1]).Authorization).toBe('Bearer abc.def.ghi');
  });

  it('401 给出可操作的提示', async () => {
    stubStorage();
    stubFetch(401);

    await expect(getJson('/runs')).rejects.toThrow(/Token/);
  });

  it('非 401 时透传后端 message（上传解析失败等）', async () => {
    stubStorage();
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: 'PARSE_FAILED', message: '扫描件没有文本层' }), {
        status: 422,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(getJson('/admin/kb/documents')).rejects.toThrow('扫描件没有文本层');
  });
});

describe('del', () => {
  it('204 不解析响应体', async () => {
    stubStorage();
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(del('/admin/budgets/u_102')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('DELETE');
  });

  it('失败时抛 ApiError（不被空响应体掩盖）', async () => {
    stubStorage();
    stubFetch(403);

    await expect(del('/admin/budgets/u_102')).rejects.toThrow('请求失败: /admin/budgets/u_102');
  });
});
