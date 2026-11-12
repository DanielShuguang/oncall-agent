/** 运行查询接口：列表、详情、断线补拉与回放。契约见 docs/03-api-contract.md 第 3 节。 */

import type { Citation, RunEvent, TimelineItem } from '@/features/chat/types';
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
  // 事件过了保留期会被整场清理（ADR-0021）；有值表示回放不可用，摘要仍可信
  events_pruned_at: string | null;
  // 正文过了保留期会被清空（ADR-0023）；有值表示 input/output 已不可读
  content_pruned_at: string | null;
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
  // 正文被保留策略清空后是空串（ADR-0023）；用 content_pruned_at 区分「本来就空」
  input: string;
  output: string | null;
  // 回答引用的文档按当前可见性回收（ADR-0022）：为 true 时 output 为 null、事件不回放
  content_redacted: boolean;
  // 历史会话还原角标用的引用快照（ADR-0031）；正文被回收/过期清理时为空
  citations: Citation[];
  // 只读运行过程（ADR-0035）：工具调用与审批，不含正文/步骤事件
  timeline: TimelineItem[];
  // false 表示事件已清理或回答被回收：过程不可用 ≠ 这轮没调工具
  timeline_available: boolean;
  timeline_truncated: boolean;
  model_calls: ModelCall[];
}

/** 批量历史里的一轮：正文/引用/运行过程，不含计量明细（ADR-0036）。 */
export type HistoryRun = Omit<RunDetail, 'model_calls'>;

export interface RunListResponse {
  items: RunSummary[];
  next_cursor: string | null;
}

export interface RunEventsResponse {
  events: RunEvent[];
  next_seq: number;
  run_status: string;
  // 引用文档不可见时事件整场不回放（ADR-0022）；与保留清理的空数组区分见详情字段
  content_redacted: boolean;
}

export function listRuns(params: {
  limit?: number;
  cursor?: string | null;
  status?: string | null;
  sessionId?: string | null;
}): Promise<RunListResponse> {
  const query = new URLSearchParams();
  if (params.limit) query.set('limit', String(params.limit));
  if (params.cursor) query.set('cursor', params.cursor);
  if (params.status) query.set('status', params.status);
  if (params.sessionId) query.set('session_id', params.sessionId);
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
