/** 工具变更历史的展示类型与格式化；与弹窗组件分开，避免单文件超行数限制。 */

import { match } from 'ts-pattern';

import type { ToolChange, ToolHistoryOrder, ToolInfo, ToolOverrideSnapshot } from '@/api/tools';

export interface HistoryState {
  tool: ToolInfo;
  loading: boolean;
  items: ToolChange[];
  error: string | null;
  changedFrom: string;
  changedTo: string;
  changedBy: string;
  source: '' | 'tool' | 'matrix' | 'rollback';
  order: ToolHistoryOrder;
  filterError: string | null;
  /** 最近一次实际查询使用的过滤；导出必须与列表一致，不能使用未应用的草稿。 */
  appliedFrom: string;
  appliedTo: string;
  appliedBy: string;
  appliedSource: '' | 'tool' | 'matrix' | 'rollback';
  appliedOrder: ToolHistoryOrder;
  /** 首屏总数；后续页为 null。 */
  total: number | null;
  nextCursor: string | null;
  loadingMore: boolean;
  /** 加载更多失败时保留已加载列表，只在底部提示。 */
  loadMoreError: string | null;
  /** 失败的后端错误码；CURSOR_EXPIRED 时提供「重新加载」（ADR-0103）。 */
  loadMoreErrorCode: string | null;
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

export function describeSnapshot(snapshot: ToolOverrideSnapshot | null): string {
  if (snapshot === null) return '代码默认';
  const enabled = snapshot.enabled === null ? '启用继承' : snapshot.enabled ? '启用' : '禁用';
  const roles =
    snapshot.roles === null
      ? '角色继承'
      : snapshot.roles.length === 0
        ? '所有登录用户'
        : snapshot.roles.join('、');
  return `${enabled} · ${roles}`;
}

export function sourceLabel(source: string): string {
  return match(source)
    .with('matrix', () => '权限矩阵')
    .with('tool', () => '工具开关')
    .with('rollback', () => '回滚')
    .otherwise((value) => value);
}
