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

export async function toApiError(res: Response, path: string): Promise<ApiError> {
  if (res.status === 401) {
    return new ApiError(401, '未登录或 token 过期：点右上角「设置 Token」');
  }
  // 后端错误统一 {code, message}；管理页要把「文件过大 / 解析失败」原样告诉用户
  let message = `请求失败: ${path}`;
  try {
    const body = (await res.json()) as { message?: unknown };
    if (typeof body.message === 'string' && body.message.trim()) message = body.message;
  } catch {
    // 非 JSON（网关 502、HTML 错误页）时保留通用文案
  }
  return new ApiError(res.status, message);
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  });
  if (!res.ok) throw await toApiError(res, path);
  return (await res.json()) as T;
}

/**
 * multipart 上传：**不要手写 Content-Type**，浏览器要自己补 boundary。
 * 单独一个函数而不是给 getJson 加分支，避免以后有人把 JSON body 和 FormData 混用。
 */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  });
  if (!res.ok) throw await toApiError(res, path);
  return (await res.json()) as T;
}

/** 无响应体的写操作（如 204 的删除）：不要试着解析 JSON。 */
export async function del(path: string): Promise<void> {
  const res = await fetch(`${PREFIX}${path}`, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) throw await toApiError(res, path);
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  env: string;
  mock_mode: boolean;
  checks: { db: string; redis: string };
}

export const getHealth = () => getJson<HealthResponse>('/health');
