/** 运行查询接口：列表、详情、断线补拉与回放。契约见 docs/03-api-contract.md 第 3 节。 */

import type { RunEvent } from '@/features/chat/types';
import { getJson } from './client';

export interface RunSummary {
  run_id: string;
  status: string;
  user_id: string;
  session_id: string;
  intent: string | null;
  model: string | null;
  step_count: number;
  max_steps: number;
  token_in: number;
  token_out: number;
  cost_cents: number;
  error_code: string | null;
  failure_category: string | null;
  event_count: number;
  started_at: string;
  finished_at: string | null;
}

export interface ModelCall {
  step: string;
  provider: string;
  model: string;
  token_in: number;
  token_out: number;
  cost_cents: number;
  latency_ms: number;
  first_token_ms: number | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface RunDetail extends RunSummary {
  input: string;
  output: string | null;
  model_calls: ModelCall[];
}

export interface RunListResponse {
  items: RunSummary[];
  next_cursor: string | null;
}

export interface RunEventsResponse {
  events: RunEvent[];
  next_seq: number;
  run_status: string;
}

export function listRuns(params: {
  limit?: number;
  cursor?: string | null;
  status?: string | null;
}): Promise<RunListResponse> {
  const query = new URLSearchParams();
  if (params.limit) query.set('limit', String(params.limit));
  if (params.cursor) query.set('cursor', params.cursor);
  if (params.status) query.set('status', params.status);
  return getJson<RunListResponse>(`/runs?${query.toString()}`);
}

export function getRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function getRunEvents(
  runId: string,
  afterSeq: number,
  limit = 200,
  signal?: AbortSignal,
): Promise<RunEventsResponse> {
  const params = new URLSearchParams({
    after_seq: String(afterSeq),
    limit: String(limit),
  });
  return getJson<RunEventsResponse>(
    `/runs/${encodeURIComponent(runId)}/events?${params.toString()}`,
    { signal },
  );
}

/** 回放要拿到完整事件流；按 next_seq 翻页，避免单页 500 条上限截断。 */
export async function getAllRunEvents(runId: string, maxPages = 20): Promise<RunEvent[]> {
  const events: RunEvent[] = [];
  let after = 0;
  for (let page = 0; page < maxPages; page += 1) {
    // 翻页依赖上一页的 next_seq，无法并行
    // oxlint-disable-next-line no-await-in-loop
    const res = await getRunEvents(runId, after, 500);
    events.push(...res.events);
    if (res.events.length === 0 || res.next_seq === after) return events;
    after = res.next_seq;
  }
  return events;
}
