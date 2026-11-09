/** 成本看板接口（W4 D19）。 */

import { getJson } from './client';

export type CostGroupBy = 'day' | 'model' | 'user';

export interface CostItem {
  key: string;
  calls: number;
  token_in: number;
  token_out: number;
  cost_cents: number;
}

export interface CostSummary {
  total_cents: number;
  calls: number;
  items: CostItem[];
}

export function getCostSummary(params: {
  from: string;
  to: string;
  groupBy: CostGroupBy;
}): Promise<CostSummary> {
  const query = new URLSearchParams({
    from: params.from,
    to: params.to,
    group_by: params.groupBy,
  });
  return getJson<CostSummary>(`/admin/cost/summary?${query.toString()}`);
}
