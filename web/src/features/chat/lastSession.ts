/** 浏览器本地记住最后一次打开的会话（ADR-0079）。 */

export const LAST_SESSION_KEY = 'oncall.last-session.v1';

type LastSessionStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): LastSessionStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalizeSessionId(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= 64 ? trimmed : null;
}

export function readLastSession(
  storage: LastSessionStorage | null = defaultStorage(),
): string | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(LAST_SESSION_KEY);
    return raw ? normalizeSessionId(raw) : null;
  } catch {
    return null;
  }
}

export function writeLastSession(
  sessionId: string,
  storage: LastSessionStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) return;
  try {
    storage.setItem(LAST_SESSION_KEY, normalized);
  } catch {
    // 隐私模式或配额不足时不影响会话本身。
  }
}

export function clearLastSession(storage: LastSessionStorage | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(LAST_SESSION_KEY);
  } catch {
    // 存储不可用时不阻断新会话。
  }
}
