import type { SessionSummary } from '@/api/sessions';

/**
 * 批量移除只允许作用于当前已加载页（ADR-0072）。
 * 搜索/刷新后不可见的会话必须从选中集合里剔除，否则确认条的数量和
 * 实际可移除的行会不一致，甚至能移除用户已看不到的会话。
 */
export function keepVisibleSelection(
  selected: Set<string>,
  sessions: SessionSummary[],
): Set<string> {
  if (selected.size === 0) return selected;
  const visible = new Set(sessions.map((item) => item.session_id));
  const next = new Set([...selected].filter((id) => visible.has(id)));
  return next.size === selected.size ? selected : next;
}
