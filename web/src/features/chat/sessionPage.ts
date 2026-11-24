import type { SessionSummary } from '@/api/sessions';

/**
 * 游标翻页期间实时聚合/置顶状态变化，已加载会话可能再次出现在后续页
 * （ADR-0033 的已知边界），直接拼接会产生重复 session_id，导致 React key
 * 冲突和重复行。重复项保持首次加载的位置；若后页副本的 updated_at 不早于
 * 已加载项，则用后页字段覆盖，避免置顶/标题停留在旧值；跳过问题仍由刷新重置。
 */
export function mergeSessionPage(
  current: SessionSummary[],
  incoming: SessionSummary[],
): SessionSummary[] {
  if (incoming.length === 0) return current;

  const indexById = new Map(current.map((item, index) => [item.session_id, index]));
  const merged = [...current];
  let changed = false;

  for (const item of incoming) {
    const index = indexById.get(item.session_id);
    if (index === undefined) {
      indexById.set(item.session_id, merged.length);
      merged.push(item);
      changed = true;
      continue;
    }

    // 同一页内重复的会话已经追加过，始终只保留第一次出现的对象。
    if (index >= current.length) continue;

    const existing = merged[index];
    if (item === existing || !isNotOlder(item.updated_at, existing.updated_at)) continue;
    merged[index] = item;
    changed = true;
  }

  return changed ? merged : current;
}

function isNotOlder(next: string, current: string): boolean {
  const nextTime = Date.parse(next);
  const currentTime = Date.parse(current);
  return Number.isFinite(nextTime) && Number.isFinite(currentTime) && nextTime >= currentTime;
}
