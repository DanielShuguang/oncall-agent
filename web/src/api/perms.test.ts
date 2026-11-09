import { afterEach, describe, expect, it, vi } from 'vitest';
import { getPermMatrix, updatePermMatrix } from './perms';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn<typeof fetch>();
  fetchMock.mockImplementation(async () => new Response(JSON.stringify(payload), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('perm matrix api', () => {
  it('GET 角色目录与工具矩阵', async () => {
    const fetchMock = stubFetch({
      roles: ['employee', 'admin'],
      tools: [{ name: 'query_cmdb', roles: [], enabled: true }],
    });

    const res = await getPermMatrix();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/admin/perm-matrix');
    expect(res.roles).toEqual(['employee', 'admin']);
    expect(res.tools[0]?.name).toBe('query_cmdb');
  });

  it('PUT 提交完整工具项（roles 空数组表示所有人）', async () => {
    const fetchMock = stubFetch({ roles: ['employee'], tools: [] });

    await updatePermMatrix([
      { name: 'query_cmdb', enabled: true, roles: [] },
      { name: 'create_ticket', enabled: false, roles: ['admin'] },
    ]);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/admin/perm-matrix');
    expect(init?.method).toBe('PUT');
    expect(JSON.parse(String(init?.body))).toEqual({
      tools: [
        { name: 'query_cmdb', enabled: true, roles: [] },
        { name: 'create_ticket', enabled: false, roles: ['admin'] },
      ],
    });
  });
});
