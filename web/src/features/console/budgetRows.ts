/** 把预算覆盖与账本用量拼成一张表（ADR-0028）。
 *
 * 纯函数：接口失败时用 null 表达「未知」，不要用 0 冒充「没花钱 / 不限」。
 */

import type { UserBudget, UserBudgetUsage } from '@/api/budgets';

export type BudgetSource = 'override' | 'default';

export interface BudgetRow {
  user_id: string;
  /** null = 今日用量还没取到或取失败 */
  spent_cents: number | null;
  /** null = 默认值还没取到（覆盖行自己的值总是已知） */
  daily_cents: number | null;
  source: BudgetSource;
  updated_by: string | null;
  updated_at: string | null;
  reservation_count: number;
  stale_count: number;
  stale_cents: number;
}

export function mergeBudgetRows(
  overrides: UserBudget[],
  defaultCents: number | null,
  usageUsers: UserBudgetUsage[] | null,
): BudgetRow[] {
  const overrideById = new Map(overrides.map((item) => [item.user_id, item]));
  const usageById = new Map((usageUsers ?? []).map((item) => [item.user_id, item]));
  // 项目 lib 是 ES2022，没有 toSorted；行数很少，用有序插入代替原地 sort
  const ids: string[] = [];
  for (const user_id of new Set([...overrideById.keys(), ...usageById.keys()])) {
    const at = ids.findIndex((item) => item > user_id);
    ids.splice(at === -1 ? ids.length : at, 0, user_id);
  }

  return ids.map((user_id) => {
    const override = overrideById.get(user_id);
    const usage = usageById.get(user_id);
    return {
      user_id,
      spent_cents: usageUsers === null ? null : (usage?.spent_cents ?? 0),
      daily_cents: override?.daily_cents ?? defaultCents,
      source: override ? 'override' : 'default',
      updated_by: override?.updated_by ?? null,
      updated_at: override?.updated_at ?? null,
      reservation_count: usage?.reservation_count ?? 0,
      stale_count: usage?.stale_count ?? 0,
      stale_cents: usage?.stale_cents ?? 0,
    } satisfies BudgetRow;
  });
}
