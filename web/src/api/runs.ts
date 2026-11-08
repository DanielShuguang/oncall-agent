/** 运行查询接口：断线后按 seq 补拉事件。契约见 docs/03-api-contract.md 第 3 节。 */

import type { RunEvent } from '@/features/chat/types';
import { getJson } from './client';

export interface RunEventsResponse {
  events: RunEvent[];
  next_seq: number;
  run_status: string;
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
