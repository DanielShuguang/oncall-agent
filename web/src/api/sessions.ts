/** 会话列表接口（ADR-0030/0033）。会话是 runs.session_id 的投影，没有独立表。 */

import type { HistoryRun } from './runs';
import { getJson } from './client';

export interface SessionSummary {
  session_id: string;
  /** 首条非空输入；正文被保留策略清空后为 null，前端显示「无标题」而不是隐藏会话 */
  title: string | null;
  run_count: number;
  started_at: string;
  updated_at: string;
}

export interface SessionPage {
  items: SessionSummary[];
  /** keyset 游标；当前页没取满时为 null（ADR-0033） */
  next_cursor: string | null;
}

export async function listSessions(limit = 20, cursor: string | null = null): Promise<SessionPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  return getJson<SessionPage>(`/sessions?${params.toString()}`);
}

export interface SessionRunsPage {
  session_id: string;
  items: HistoryRun[];
  /** 与 /runs 同一套 keyset 游标；取满才返回（ADR-0036） */
  next_cursor: string | null;
}

/** 一次取回一页会话详情（ADR-0036），替代详情 + 事件的 N+1 请求。 */
export async function getSessionRuns(
  sessionId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<SessionRunsPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  return getJson<SessionRunsPage>(
    `/sessions/${encodeURIComponent(sessionId)}/runs?${params.toString()}`,
  );
}
