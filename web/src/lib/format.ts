/** 展示层格式化：金额、时间、状态与失败归因的统一口径。 */

import dayjs from 'dayjs';

export function formatCents(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`;
}

export function formatTime(value: string | null | undefined): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';
}

export function formatDuration(start: string, end: string | null): string {
  if (!end) return '-';
  const ms = dayjs(end).diff(dayjs(start));
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/** 毫秒时长的统一展示：<1s 用 ms，<1min 保留 1 位小数，再进位到分/时/天。 */
export function formatDurationMs(durationMs: number): string {
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

export const STATUS_LABELS: Record<string, string> = {
  running: '执行中',
  awaiting_approval: '待审批',
  completed: '已完成',
  failed: '失败',
  interrupted: '已中断',
};

export const STATUS_TONES: Record<string, string> = {
  running: 'border-brand/20 bg-brand/10 text-brand',
  awaiting_approval: 'border-warn/20 bg-warn/10 text-warn',
  completed: 'border-ok/20 bg-ok/10 text-ok',
  failed: 'border-danger/20 bg-danger/10 text-danger',
  interrupted: 'border-line bg-muted text-muted-foreground',
};

export const FAILURE_LABELS: Record<string, string> = {
  model: '模型',
  tool: '工具',
  approval: '审批',
  limit: '护栏',
  internal: '内部',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function failureLabel(category: string | null): string {
  if (!category) return '-';
  return FAILURE_LABELS[category] ?? category;
}
