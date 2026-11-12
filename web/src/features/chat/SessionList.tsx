/** 会话侧栏（ADR-0030）：只展示服务端投影，不在浏览器本地缓存会话。 */

import { Pencil } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { SessionSummary } from '@/api/sessions';
import { cn } from 'cn';

interface SessionListProps {
  sessions: SessionSummary[];
  activeSessionId: string;
  loading: boolean;
  error: string | null;
  /** 历史会话正在加载：暂时锁住列表项，避免连点导致后到的响应覆盖前一次选择 */
  busy: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  /** 已提交的搜索词（ADR-0039），只用于空态文案 */
  query: string;
  searchDraft: string;
  onSearchDraftChange: (value: string) => void;
  onSearch: () => void;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
  /** 正在改名的会话（ADR-0040）；null 表示没有行内编辑 */
  renamingId: string | null;
  renameDraft: string;
  renameSaving: boolean;
  onRenameStart: (session: SessionSummary) => void;
  onRenameDraftChange: (value: string) => void;
  onRenameSubmit: () => void;
  onRenameCancel: () => void;
}

function formatUpdated(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function SessionList({
  sessions,
  activeSessionId,
  loading,
  error,
  busy,
  hasMore,
  loadingMore,
  query,
  searchDraft,
  onSearchDraftChange,
  onSearch,
  onSelect,
  onNew,
  onRetry,
  onLoadMore,
  renamingId,
  renameDraft,
  renameSaving,
  onRenameStart,
  onRenameDraftChange,
  onRenameSubmit,
  onRenameCancel,
}: SessionListProps) {
  return (
    <aside className="hidden w-56 shrink-0 flex-col gap-2 border-r p-3 sm:flex">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">会话</span>
        <Button size="sm" variant="outline" onClick={onNew}>
          新会话
        </Button>
      </div>

      <form
        className="flex gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <input
          value={searchDraft}
          onChange={(event) => onSearchDraftChange(event.target.value)}
          placeholder="搜索标题"
          aria-label="搜索会话标题"
          className="h-8 min-w-0 flex-1 rounded-md border bg-transparent px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-brand/40"
        />
        <Button size="sm" variant="outline" type="submit">
          搜索
        </Button>
      </form>

      {loading && <p className="px-1 py-2 text-xs text-muted-foreground">加载中…</p>}
      {error && (
        <div className="space-y-1 px-1 py-2">
          <p className="text-xs text-danger">{error}</p>
          <Button size="sm" variant="outline" onClick={() => onRetry()}>
            重试
          </Button>
        </div>
      )}
      {!loading && !error && sessions.length === 0 && (
        <p className="px-1 py-2 text-xs text-muted-foreground">
          {query.trim() ? '没有匹配的会话。' : '还没有历史会话。'}
        </p>
      )}

      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {sessions.map((session) => {
          const active = session.session_id === activeSessionId;
          if (session.session_id === renamingId) {
            return (
              <li key={session.session_id}>
                <form
                  className="flex flex-col gap-1 rounded-md border bg-canvas p-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    onRenameSubmit();
                  }}
                >
                  <input
                    value={renameDraft}
                    maxLength={60}
                    disabled={renameSaving}
                    onChange={(event) => onRenameDraftChange(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        onRenameCancel();
                      }
                    }}
                    aria-label="会话标题"
                    placeholder="最多 60 字，留空恢复默认"
                    className="h-8 w-full rounded-md border bg-transparent px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-brand/40"
                  />
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="outline" type="button" onClick={onRenameCancel}>
                      取消
                    </Button>
                    <Button size="sm" type="submit" disabled={busy || renameSaving}>
                      {renameSaving ? '保存中…' : '保存'}
                    </Button>
                  </div>
                </form>
              </li>
            );
          }
          return (
            <li key={session.session_id}>
              <div className="flex items-start gap-1">
                <button
                  type="button"
                  aria-current={active ? 'true' : undefined}
                  disabled={busy}
                  className={cn(
                    'min-w-0 flex-1 rounded-md px-2 py-1.5 text-left text-xs hover:bg-canvas disabled:cursor-default disabled:opacity-60',
                    active && 'bg-canvas font-medium',
                  )}
                  onClick={() => onSelect(session.session_id)}
                >
                  <span className="line-clamp-2 break-words">{session.title ?? '无标题'}</span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {session.run_count} 轮 · {formatUpdated(session.updated_at)}
                  </span>
                </button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 shrink-0 px-1.5"
                  aria-label={`重命名会话 ${session.title ?? '无标题'}`}
                  disabled={busy}
                  onClick={() => onRenameStart(session)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
              </div>
            </li>
          );
        })}
      </ul>

      {hasMore && (
        <Button size="sm" variant="outline" disabled={loadingMore || busy} onClick={onLoadMore}>
          {loadingMore ? '加载中…' : '加载更多会话'}
        </Button>
      )}
    </aside>
  );
}
