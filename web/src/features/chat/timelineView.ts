/** 运行过程折叠区的纯视图逻辑（ADR-0045）。
 *
 * 只处理服务端已经裁到 20 项的时间线：筛选与耗时聚合都在客户端做，
 * 不改变 `/sessions/{id}/runs` 的契约，也不引入额外请求。
 */

import type { ApprovalTimelineItem, TimelineItem, ToolTimelineItem } from './types';

export type TimelineKindFilter = 'all' | 'tool' | 'approval' | 'problem';

export interface TimelineSummary {
  toolCount: number;
  approvalCount: number;
  /** 所有带 duration_ms 的工具调用之和；毫秒整数。 */
  totalDurationMs: number;
  /** 最慢的一次工具调用；没有耗时时为 null。 */
  slowest: { tool: string; durationMs: number } | null;
  /** 失败/超时/被拒绝的工具，以及被拒绝/过期的审批。 */
  problemCount: number;
}

const PROBLEM_TOOL_STATUS = new Set(['error', 'timeout', 'denied']);
const PROBLEM_APPROVAL_STATUS = new Set(['rejected', 'expired']);

function isApproval(item: TimelineItem): item is ApprovalTimelineItem {
  return item.kind === 'approval';
}

function isTool(item: TimelineItem): item is ToolTimelineItem {
  return item.kind === 'tool';
}

export function isProblemItem(item: TimelineItem): boolean {
  return isTool(item)
    ? PROBLEM_TOOL_STATUS.has(item.status)
    : PROBLEM_APPROVAL_STATUS.has(item.status);
}

export function summarizeTimeline(items: TimelineItem[]): TimelineSummary {
  let toolCount = 0;
  let approvalCount = 0;
  let totalDurationMs = 0;
  let problemCount = 0;
  let slowest: { tool: string; durationMs: number } | null = null;

  for (const item of items) {
    if (isTool(item)) {
      toolCount += 1;
      if (typeof item.duration_ms === 'number' && item.duration_ms >= 0) {
        totalDurationMs += item.duration_ms;
        if (slowest === null || item.duration_ms > slowest.durationMs) {
          slowest = { tool: item.tool, durationMs: item.duration_ms };
        }
      }
    } else {
      approvalCount += 1;
    }
    if (isProblemItem(item)) problemCount += 1;
  }

  return { toolCount, approvalCount, totalDurationMs, slowest, problemCount };
}

export function filterTimeline(
  items: TimelineItem[],
  { kind, tool }: { kind: TimelineKindFilter; tool: string },
): TimelineItem[] {
  const needle = tool.trim().toLowerCase();
  return items.filter((item) => {
    if (kind === 'tool' && !isTool(item)) return false;
    if (kind === 'approval' && !isApproval(item)) return false;
    if (kind === 'problem' && !isProblemItem(item)) return false;
    if (needle && !item.tool.toLowerCase().includes(needle)) return false;
    return true;
  });
}

export function formatDuration(durationMs: number): string {
  const clamped = Math.max(0, durationMs);
  if (clamped < 1000) return `${Math.round(clamped)}ms`;
  const totalSeconds = clamped / 1000;
  // 59.95s 以上一律进位到「分」，否则 119999ms 会显示成「1m 60s」。
  if (totalSeconds < 59.95) {
    const seconds = totalSeconds.toFixed(1);
    return `${seconds.endsWith('.0') ? seconds.slice(0, -2) : seconds}s`;
  }
  const wholeSeconds = Math.round(totalSeconds);
  if (wholeSeconds < 3600) {
    return `${Math.floor(wholeSeconds / 60)}m ${wholeSeconds % 60}s`;
  }
  // 审批等待可能以小时/天计，不能一直堆成「1440m 0s」。
  const wholeMinutes = Math.floor(wholeSeconds / 60);
  if (wholeMinutes < 1440) {
    return `${Math.floor(wholeMinutes / 60)}h ${wholeMinutes % 60}m`;
  }
  const wholeHours = Math.floor(wholeMinutes / 60);
  return `${Math.floor(wholeHours / 24)}d ${wholeHours % 24}h`;
}
