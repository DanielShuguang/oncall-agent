/** 会话侧栏（ADR-0030）：只展示服务端投影，不在浏览器本地缓存会话。 */

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
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
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
  onSelect,
  onNew,
  onRetry,
  onLoadMore,
}: SessionListProps) {
  return (
    <aside className="hidden w-56 shrink-0 flex-col gap-2 border-r p-3 sm:flex">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">会话</span>
        <Button size="sm" variant="outline" onClick={onNew}>
          新会话
        </Button>
      </div>

      {loading && <p className="px-1 py-2 text-xs text-muted-foreground">加载中…</p>}
      {error && (
        <div className="space-y-1 px-1 py-2">
          <p className="text-xs text-danger">{error}</p>
          <Button size="sm" variant="outline" onClick={onRetry}>
            重试
          </Button>
        </div>
      )}
      {!loading && !error && sessions.length === 0 && (
        <p className="px-1 py-2 text-xs text-muted-foreground">还没有历史会话。</p>
      )}

      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {sessions.map((session) => {
          const active = session.session_id === activeSessionId;
          return (
            <li key={session.session_id}>
              <button
                type="button"
                aria-current={active ? 'true' : undefined}
                disabled={busy}
                className={cn(
                  'w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-canvas disabled:cursor-default disabled:opacity-60',
                  active && 'bg-canvas font-medium',
                )}
                onClick={() => onSelect(session.session_id)}
              >
                <span className="line-clamp-2 break-words">{session.title ?? '无标题'}</span>
                <span className="mt-0.5 block text-[11px] text-muted-foreground">
                  {session.run_count} 轮 · {formatUpdated(session.updated_at)}
                </span>
              </button>
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
