/** 会话列表接口（ADR-0030/0033）。会话是 runs.session_id 的投影，没有独立表。 */

import type { HistoryRun } from './runs';
import { del, getJson, patch, postJson } from './client';

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

export async function listSessions(
  limit = 20,
  cursor: string | null = null,
  query: string | null = null,
): Promise<SessionPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  if (query) params.set('q', query);
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

/** 改会话显示标题（ADR-0040）；传 null 恢复默认（首条问题）。 */
export async function renameSession(sessionId: string, title: string | null): Promise<void> {
  await patch(`/sessions/${encodeURIComponent(sessionId)}`, { title });
}

/** 从会话列表移除（ADR-0041，软移除）；run/事件仍按保留期保存。 */
export async function hideSession(sessionId: string): Promise<void> {
  await del(`/sessions/${encodeURIComponent(sessionId)}`);
}

export interface HiddenSession {
  session_id: string;
  title: string | null;
  run_count: number;
  hidden_at: string;
}

export interface HiddenSessionPage {
  items: HiddenSession[];
  next_cursor: string | null;
}

/** 已移除的会话（ADR-0043 / ADR-0047）；只影响列表，run/事件仍按保留期保存。 */
export async function listHiddenSessions(
  limit = 50,
  cursor: string | null = null,
  query: string | null = null,
): Promise<HiddenSessionPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  if (query) params.set('q', query);
  return getJson<HiddenSessionPage>(`/sessions/hidden?${params.toString()}`);
}

/** 恢复已移除的会话（ADR-0043）：只删 hidden_sessions 行，恢复后重新参与列表与搜索。 */
export async function restoreSession(sessionId: string): Promise<void> {
  await del(`/sessions/${encodeURIComponent(sessionId)}/hidden`);
}

export interface RestoreSessionsItem {
  session_id: string;
  restored: boolean;
}

export interface RestoreSessionsResult {
  restored: number;
  requested: number;
  /** 与去重后的请求顺序一致；false 表示不存在、属于别人或本来就没移除（ADR-0055） */
  items: RestoreSessionsItem[];
}

/** 批量恢复（ADR-0049/0055）：最多 50 个，去重后处理；逐条返回是否真正恢复。 */
export async function restoreSessions(sessionIds: string[]): Promise<RestoreSessionsResult> {
  return postJson<RestoreSessionsResult>('/sessions/hidden/restore', {
    session_ids: sessionIds,
  });
}
