/** 会话列表接口（ADR-0030）。会话是 runs.session_id 的投影，没有独立表。 */

import { getJson } from './client';

export interface SessionSummary {
  session_id: string;
  /** 首条非空输入；正文被保留策略清空后为 null，前端显示「无标题」而不是隐藏会话 */
  title: string | null;
  run_count: number;
  started_at: string;
  updated_at: string;
}

interface SessionListResponse {
  items: SessionSummary[];
  next_cursor: string | null;
}

export async function listSessions(limit = 20): Promise<SessionSummary[]> {
  const res = await getJson<SessionListResponse>(`/sessions?limit=${limit}`);
  return res.items;
}
