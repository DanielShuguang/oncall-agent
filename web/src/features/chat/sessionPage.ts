import type { SessionSummary } from '@/api/sessions';

/**
 * 游标翻页期间可能有新 run 让会话移动到下一页（ADR-0033 的已知边界），
 * 直接拼接会产生重复 session_id，导致 React key 冲突和重复行。
 * 保留已加载项的顺序，只追加新出现的会话；跳过问题仍由刷新重置解决。
 */
export function mergeSessionPage(
  current: SessionSummary[],
  incoming: SessionSummary[],
): SessionSummary[] {
  if (incoming.length === 0) return current;
  const seen = new Set(current.map((item) => item.session_id));
  const merged = [...current];
  for (const item of incoming) {
    if (seen.has(item.session_id)) continue;
    seen.add(item.session_id);
    merged.push(item);
  }
  return merged;
}
