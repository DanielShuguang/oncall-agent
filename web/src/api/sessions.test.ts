import { afterEach, describe, expect, it, vi } from 'vitest';

import { hideSessions, pinSession, unpinSession } from './sessions';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('session pin', () => {
  it('置顶用无 body POST，取消用 DELETE，路径按 session_id 编码', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await pinSession('sess a');
    await unpinSession('sess a');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/sessions/sess%20a/pin');
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/sessions/sess%20a/pin');
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('DELETE');
  });
});

describe('session batch hide', () => {
  it('批量移除发送 session_ids 并解析逐条结果', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            hidden: 1,
            requested: 2,
            items: [
              { session_id: 'sess_a', hidden: true },
              { session_id: 'sess_b', hidden: false },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await hideSessions(['sess_a', 'sess_b']);

    expect(result.hidden).toBe(1);
    expect(result.items[1]).toEqual({ session_id: 'sess_b', hidden: false });
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/sessions/hide');
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({ session_ids: ['sess_a', 'sess_b'] }),
    );
  });
});
