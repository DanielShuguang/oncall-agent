/** 按用户日预算接口（ADR-0026）：默认值 + 按用户覆盖，单位「分」，0 = 不限。 */

import { del, getJson } from './client';

export interface UserBudget {
  user_id: string;
  daily_cents: number;
  updated_by: string;
  updated_at: string | null;
}

export interface UserBudgetList {
  default_cents: number;
  overrides: UserBudget[];
}

/** 账本快照里的预扣统计（ADR-0028）；oldest_age_s 为 null 表示没有可读时间戳。 */
export interface ReservationStats {
  reserved_cents: number;
  reservation_count: number;
  stale_count: number;
  stale_cents: number;
  oldest_age_s: number | null;
}

export interface GlobalBudgetUsage extends ReservationStats {
  /** 配置的全局日上限（分）；0 = 不限 */
  limit_cents: number;
  /** 含未结算预扣，口径不是 model_calls 的实际成本 */
  spent_cents: number;
}

export interface UserBudgetUsage extends ReservationStats {
  user_id: string;
  spent_cents: number;
}

export interface BudgetUsage {
  day: string;
  stale_after_s: number;
  global_usage: GlobalBudgetUsage;
  /** 只含有过预扣/花费的用户；表格需要再与覆盖列表 union */
  users: UserBudgetUsage[];
}

export function listBudgets(): Promise<UserBudgetList> {
  return getJson<UserBudgetList>('/admin/budgets');
}

export function getBudgetUsage(): Promise<BudgetUsage> {
  return getJson<BudgetUsage>('/admin/budgets/usage');
}

export function setBudget(userId: string, dailyCents: number): Promise<UserBudget> {
  return getJson<UserBudget>(`/admin/budgets/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify({ daily_cents: dailyCents }),
  });
}

/** 删除覆盖、回到环境默认值；204 无响应体，不能走 getJson。 */
export function clearBudget(userId: string): Promise<void> {
  return del(`/admin/budgets/${encodeURIComponent(userId)}`);
}
