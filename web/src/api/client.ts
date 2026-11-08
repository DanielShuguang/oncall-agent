/** 极简 API 客户端：统一前缀、统一错误。正式类型由 gen:api 生成。 */

const PREFIX = '/api';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new ApiError(res.status, `请求失败: ${path}`);
  return (await res.json()) as T;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  env: string;
  mock_mode: boolean;
  checks: { db: string; redis: string };
}

export const getHealth = () => getJson<HealthResponse>('/health');
