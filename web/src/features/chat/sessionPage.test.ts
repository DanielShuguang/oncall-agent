import { describe, expect, it } from 'vitest';
import type { SessionSummary } from '@/api/sessions';
import { mergeSessionPage } from './sessionPage';

function session(sessionId: string, overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    session_id: sessionId,
    title: sessionId,
    started_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    run_count: 1,
    pinned: false,
    ...overrides,
  };
}

describe('mergeSessionPage', () => {
  it('跳过已加载的 session_id，只追加新会话', () => {
    const current = [session('a'), session('b')];
    const merged = mergeSessionPage(current, [session('b'), session('c')]);
    expect(merged.map((item) => item.session_id)).toEqual(['a', 'b', 'c']);
  });

  it('同一页内重复也只保留第一次出现', () => {
    const merged = mergeSessionPage([], [session('a'), session('a'), session('b')]);
    expect(merged.map((item) => item.session_id)).toEqual(['a', 'b']);
  });

  it('重复会话用不早于已加载项的后页字段覆盖', () => {
    const current = [session('a', { pinned: true })];
    const merged = mergeSessionPage(current, [session('a', { pinned: false })]);
    expect(merged).toHaveLength(1);
    expect(merged[0]?.pinned).toBe(false);
  });

  it('较早的后页副本不覆盖已加载项', () => {
    const current = [session('a', { title: '新标题' })];
    const incoming = session('a', {
      title: '旧标题',
      updated_at: '2025-12-31T00:00:00Z',
    });
    expect(mergeSessionPage(current, [incoming])).toBe(current);
  });

  it('空页保持原引用，避免无意义渲染', () => {
    const current = [session('a')];
    expect(mergeSessionPage(current, [])).toBe(current);
  });
});
