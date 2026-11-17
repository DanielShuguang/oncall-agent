import { describe, expect, it } from 'vitest';
import type { SessionSummary } from '@/api/sessions';
import { keepVisibleSelection } from './sessionSelection';

function session(sessionId: string): SessionSummary {
  return {
    session_id: sessionId,
    title: sessionId,
    run_count: 1,
    started_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

describe('keepVisibleSelection', () => {
  it('空选择保持原引用', () => {
    const selected = new Set<string>();
    expect(keepVisibleSelection(selected, [session('a')])).toBe(selected);
  });

  it('剔除已不在当前页的会话，保留仍可见的选中项', () => {
    const selected = new Set(['a', 'b', 'c']);
    const next = keepVisibleSelection(selected, [session('a'), session('c'), session('d')]);
    expect([...next]).toEqual(['a', 'c']);
  });

  it('选择完全落在当前页时保持原引用', () => {
    const selected = new Set(['a', 'b']);
    expect(keepVisibleSelection(selected, [session('a'), session('b')])).toBe(selected);
  });

  it('当前页没有会话时清空选择', () => {
    const selected = new Set(['a']);
    expect(keepVisibleSelection(selected, [])).toEqual(new Set());
  });
});
