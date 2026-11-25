/** 已移除会话的折叠区（ADR-0043/0047/0049/0055）。 */

import type { HiddenSession } from '@/api/sessions';
import { Button } from '@/components/ui/button';
import { formatUpdated } from './sessionFormat';

interface HiddenSessionsPanelProps {
  open: boolean;
  sessions: HiddenSession[];
  loading: boolean;
  error: string | null;
  notice: string | null;
  query: string;
  draftQuery: string;
  hasMore: boolean;
  loadingMore: boolean;
  restoringId: string | null;
  restoringBatch: boolean;
  selected: Set<string>;
  allSelected: boolean;
  onToggle: () => void;
  onDraftChange: (value: string) => void;
  onSearch: () => void;
  onLoadMore: () => void;
  onToggleSelect: (sessionId: string) => void;
  onToggleAll: () => void;
  onRestoreSelected: () => void;
  onRestore: (sessionId: string) => void;
}

export function HiddenSessionsPanel({
  open,
  sessions,
  loading,
  error,
  notice,
  query,
  draftQuery,
  hasMore,
  loadingMore,
  restoringId,
  restoringBatch,
  selected,
  allSelected,
  onToggle,
  onDraftChange,
  onSearch,
  onLoadMore,
  onToggleSelect,
  onToggleAll,
  onRestoreSelected,
  onRestore,
}: HiddenSessionsPanelProps) {
  return (
    <div className="border-t pt-2">
      <Button
        size="sm"
        variant="ghost"
        className="w-full justify-start text-muted-foreground"
        aria-expanded={open}
        aria-controls="hidden-sessions"
        onClick={onToggle}
      >
        {open ? '收起已移除的会话' : '已移除的会话'}
      </Button>
      {open && (
        <div id="hidden-sessions" className="mt-1 max-h-56 space-y-1 overflow-y-auto pr-1">
          <form
            className="flex gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              onSearch();
            }}
          >
            <input
              value={draftQuery}
              onChange={(event) => onDraftChange(event.target.value)}
              placeholder="搜索已移除"
              aria-label="搜索已移除的会话"
              className="h-7 min-w-0 flex-1 rounded-md border bg-transparent px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-brand/40"
            />
            <Button size="sm" variant="outline" type="submit">
              搜索
            </Button>
          </form>
          <div className="flex items-center justify-between gap-1 px-1">
            <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={onToggleAll}
                disabled={sessions.length === 0 || restoringBatch || restoringId !== null}
                aria-label="全选已加载的已移除会话"
              />
              全选
            </label>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.size === 0 || restoringBatch || restoringId !== null}
              onClick={onRestoreSelected}
            >
              {restoringBatch ? '恢复中…' : `恢复选中（${selected.size}）`}
            </Button>
          </div>
          {loading && <p className="px-1 py-1 text-xs text-muted-foreground">加载中…</p>}
          {error && <p className="px-1 py-1 text-xs text-danger">{error}</p>}
          {notice && (
            <p className="px-1 py-1 text-xs text-muted-foreground" aria-live="polite">
              {notice}
            </p>
          )}
          {!loading && !error && sessions.length === 0 && (
            <p className="px-1 py-1 text-xs text-muted-foreground">
              {query.trim() ? '没有匹配的已移除会话。' : '没有已移除的会话。'}
            </p>
          )}
          {sessions.map((item) => (
            <div
              key={item.session_id}
              className="flex items-start gap-1.5 rounded-md border bg-canvas p-1.5"
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={selected.has(item.session_id)}
                onChange={() => onToggleSelect(item.session_id)}
                aria-label={`选择已移除会话 ${item.title ?? '无标题'}`}
                disabled={restoringBatch}
              />
              <div className="min-w-0 flex-1">
                <span className="line-clamp-2 wrap-break-word text-xs">
                  {item.title ?? '无标题'}
                </span>
                <span className="block text-[11px] text-muted-foreground">
                  {item.run_count} 轮 · 移除于 {formatUpdated(item.hidden_at)}
                  {item.was_pinned ? ' · 移除时置顶（恢复按容量尽力）' : ''}
                </span>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={restoringId !== null || restoringBatch}
                onClick={() => onRestore(item.session_id)}
              >
                {restoringId === item.session_id ? '恢复中…' : '恢复'}
              </Button>
            </div>
          ))}
          {hasMore && (
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              disabled={loadingMore || loading}
              onClick={onLoadMore}
            >
              {loadingMore ? '加载中…' : '加载更多'}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
