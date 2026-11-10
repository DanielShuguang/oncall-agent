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

export function listBudgets(): Promise<UserBudgetList> {
  return getJson<UserBudgetList>('/admin/budgets');
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
