import { describe, expect, it } from 'vitest';

import type { ApprovalTimelineItem, TimelineItem, ToolTimelineItem } from './types';
import { filterTimeline, formatDuration, summarizeTimeline } from './timelineView';

function tool(overrides: Partial<ToolTimelineItem> = {}): ToolTimelineItem {
  return {
    kind: 'tool',
    seq: 1,
    call_id: 'call_1',
    tool: 'query_cmdb',
    args: {},
    write: false,
    status: 'ok',
    ...overrides,
  };
}

function approval(overrides: Partial<ApprovalTimelineItem> = {}): ApprovalTimelineItem {
  return {
    kind: 'approval',
    seq: 2,
    approval_id: 'apr_1',
    tool: 'create_ticket',
    args: {},
    risk_level: 'high',
    status: 'approved',
    ...overrides,
  };
}

describe('summarizeTimeline', () => {
  it('counts items, sums durations and finds the slowest tool', () => {
    const items: TimelineItem[] = [
      tool({ seq: 1, duration_ms: 1200 }),
      tool({ seq: 2, tool: 'create_ticket', status: 'error', duration_ms: 300 }),
      approval({ seq: 3, status: 'rejected' }),
    ];
    expect(summarizeTimeline(items)).toEqual({
      toolCount: 2,
      approvalCount: 1,
      totalDurationMs: 1500,
      slowest: { tool: 'query_cmdb', durationMs: 1200 },
      problemCount: 2,
    });
  });

  it('handles timelines without durations or items', () => {
    expect(summarizeTimeline([])).toEqual({
      toolCount: 0,
      approvalCount: 0,
      totalDurationMs: 0,
      slowest: null,
      problemCount: 0,
    });
    expect(summarizeTimeline([tool({ duration_ms: undefined })]).slowest).toBeNull();
  });
});

describe('filterTimeline', () => {
  const items: TimelineItem[] = [
    tool({ seq: 1 }),
    tool({ seq: 2, tool: 'query_tickets', status: 'timeout' }),
    approval({ seq: 3, status: 'expired' }),
  ];

  it('filters by kind', () => {
    expect(filterTimeline(items, { kind: 'tool', tool: '' })).toHaveLength(2);
    expect(filterTimeline(items, { kind: 'approval', tool: '' })).toHaveLength(1);
    expect(filterTimeline(items, { kind: 'problem', tool: '' }).map((item) => item.seq)).toEqual([
      2, 3,
    ]);
  });

  it('matches tool names case-insensitively and combines with kind', () => {
    expect(
      filterTimeline(items, { kind: 'all', tool: '  QUERY_' }).map((item) => item.seq),
    ).toEqual([1, 2]);
    expect(filterTimeline(items, { kind: 'tool', tool: 'ticket' }).map((item) => item.seq)).toEqual(
      [2],
    );
    expect(filterTimeline(items, { kind: 'all', tool: 'missing' })).toEqual([]);
  });
});

describe('formatDuration', () => {
  it('switches units at second and minute boundaries', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(999)).toBe('999ms');
    expect(formatDuration(1000)).toBe('1s');
    expect(formatDuration(1200)).toBe('1.2s');
    expect(formatDuration(59_949)).toBe('59.9s');
    expect(formatDuration(59_999)).toBe('1m 0s');
    expect(formatDuration(60_000)).toBe('1m 0s');
    expect(formatDuration(119_999)).toBe('2m 0s');
    expect(formatDuration(63_000)).toBe('1m 3s');
    expect(formatDuration(3_599_000)).toBe('59m 59s');
  });

  it('switches to hours and days for long approval waits', () => {
    expect(formatDuration(3_600_000)).toBe('1h 0m');
    expect(formatDuration(5_430_000)).toBe('1h 30m');
    expect(formatDuration(86_399_000)).toBe('23h 59m');
    expect(formatDuration(86_400_000)).toBe('1d 0h');
    expect(formatDuration(90_061_000)).toBe('1d 1h');
  });
});
