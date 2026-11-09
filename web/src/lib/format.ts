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
