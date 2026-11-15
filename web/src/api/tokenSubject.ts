/**
 * 只解析本地 JWT 的 `sub`，用于区分本地偏好的归属；不验签、不用于权限判断。
 * 解析失败返回 null，调用方应把它当作「无法判断账号」而不是任意用户。
 */
export function tokenSubject(token: string | null | undefined): string | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;

  try {
    const payload = JSON.parse(decodeBase64Url(parts[1])) as unknown;
    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
    const sub = (payload as Record<string, unknown>).sub;
    if (typeof sub !== 'string') return null;
    return sub.trim() || null;
  } catch {
    return null;
  }
}

/** 只在新 token 能识别出 subject 且与旧 subject 不同（含从无 token 切换）时清理。 */
export function shouldClearLocalPreferences(
  previousToken: string | null,
  nextToken: string | null,
): boolean {
  const nextSubject = tokenSubject(nextToken);
  return Boolean(nextSubject) && nextSubject !== tokenSubject(previousToken);
}

function decodeBase64Url(segment: string): string {
  const base64 = segment.replaceAll('-', '+').replaceAll('_', '/');
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(base64 + padding);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
