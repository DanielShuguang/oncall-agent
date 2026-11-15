import { afterEach, describe, expect, it, vi } from 'vitest';

import { pinSession, unpinSession } from './sessions';

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
