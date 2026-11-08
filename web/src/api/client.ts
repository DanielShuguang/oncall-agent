/** 极简 API 客户端：统一前缀、统一错误、统一带 Bearer token。正式类型由 gen:api 生成。 */

const PREFIX = '/api';
const TOKEN_KEY = 'oncall.token';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // 隐私模式 / 禁用存储
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // 存不了就只影响刷新后保持登录，不阻断本次请求
  }
}

/** W1 用本地签发 JWT（docs/03 §0）；接 SSO 后换成 cookie/刷新逻辑。 */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  });
  if (!res.ok) {
    throw new ApiError(
      res.status,
      res.status === 401 ? '未登录或 token 过期：点右上角「设置 Token」' : `请求失败: ${path}`,
    );
  }
  return (await res.json()) as T;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  env: string;
  mock_mode: boolean;
  checks: { db: string; redis: string };
}

export const getHealth = () => getJson<HealthResponse>('/health');
