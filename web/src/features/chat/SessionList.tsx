/** 会话侧栏（ADR-0030）：只展示服务端投影，不在浏览器本地缓存会话。 */

import { useEffect, useRef, useState } from 'react';
import { MessageSquare, Pencil, Pin, Plus, Search, Trash2, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { HiddenSession, SessionSummary } from '@/api/sessions';
import { cn } from 'cn';

interface SessionListProps {
  sessions: SessionSummary[];
  activeSessionId: string;
  /** 窄屏抽屉是否打开（ADR-0076）；≥sm 时侧栏常驻，不受此值影响 */
  mobileOpen: boolean;
  onCloseMobile: () => void;
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
  /** 正在置顶/取消置顶的会话（ADR-0069） */
  pinningId: string | null;
  pinnedCount: number | null;
  pinLimit: number | null;
  onTogglePin: (session: SessionSummary) => void;
  /** 正在从列表移除的会话（ADR-0041） */
  hidingId: string | null;
  onHide: (sessionId: string) => void;
  /** 批量移除（ADR-0072）：管理模式下多选当前已加载页 */
  batchMode: boolean;
  batchSelected: Set<string>;
  batchHiding: boolean;
  batchNotice: string | null;
  onToggleBatchMode: () => void;
  onBatchToggleSelect: (sessionId: string) => void;
  onBatchToggleAll: () => void;
  onHideSelected: () => void;
  /** 已移除的会话折叠区（ADR-0043） */
  hiddenOpen: boolean;
  hiddenSessions: HiddenSession[];
  hiddenLoading: boolean;
  hiddenError: string | null;
  /** 批量恢复后的部分成功提示（ADR-0055）；不占用错误样式 */
  hiddenNotice: string | null;
  /** 已移除视图的搜索与分页（ADR-0047） */
  hiddenQuery: string;
  hiddenDraftQuery: string;
  hiddenHasMore: boolean;
  hiddenLoadingMore: boolean;
  onHiddenDraftChange: (value: string) => void;
  onHiddenSearch: () => void;
  onHiddenLoadMore: () => void;
  restoringId: string | null;
  /** 批量恢复（ADR-0049）：选中只覆盖当前已加载页 */
  restoringBatch: boolean;
  hiddenSelected: Set<string>;
  onHiddenToggleSelect: (sessionId: string) => void;
  onHiddenToggleAll: () => void;
  onRestoreSelected: () => void;
  onToggleHidden: () => void;
  onRestore: (sessionId: string) => void;
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
  mobileOpen,
  onCloseMobile,
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
  pinningId,
  pinnedCount,
  pinLimit,
  onTogglePin,
  hidingId,
  onHide,
  batchMode,
  batchSelected,
  batchHiding,
  batchNotice,
  onToggleBatchMode,
  onBatchToggleSelect,
  onBatchToggleAll,
  onHideSelected,
  hiddenOpen,
  hiddenSessions,
  hiddenLoading,
  hiddenError,
  hiddenNotice,
  hiddenQuery,
  hiddenDraftQuery,
  hiddenHasMore,
  hiddenLoadingMore,
  onHiddenDraftChange,
  onHiddenSearch,
  onHiddenLoadMore,
  restoringId,
  restoringBatch,
  hiddenSelected,
  onHiddenToggleSelect,
  onHiddenToggleAll,
  onRestoreSelected,
  onToggleHidden,
  onRestore,
}: SessionListProps) {
  // 行内二次确认，避免为一次移除引入额外的全局弹层（ADR-0041）
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  // 批量移除的二次确认（ADR-0072）
  const [confirmingBatch, setConfirmingBatch] = useState(false);
  const mobileCloseButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    // 只把焦点移入抽屉，不做焦点陷阱（ADR-0076 决策 6）。
    if (window.matchMedia('(max-width: 639px)').matches) {
      mobileCloseButton.current?.focus();
    }
  }, [mobileOpen]);
  const allBatchSelected =
    sessions.length > 0 && sessions.every((item) => batchSelected.has(item.session_id));
  const pinLimitReached = pinnedCount !== null && pinLimit !== null && pinnedCount >= pinLimit;
  const allHiddenSelected =
    hiddenSessions.length > 0 &&
    hiddenSessions.every((item) => hiddenSelected.has(item.session_id));
  return (
    <aside
      id="session-list"
      aria-label="会话列表"
      className={cn(
        'w-72 shrink-0 flex-col gap-3 border-r bg-panel p-3',
        mobileOpen
          ? 'fixed inset-y-0 left-0 z-40 flex shadow-xl sm:static sm:z-auto sm:shadow-none'
          : 'hidden sm:flex',
      )}
    >
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground">会话</span>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={batchMode ? 'secondary' : 'ghost'}
            className="h-7 px-2 text-xs"
            aria-pressed={batchMode}
            onClick={() => {
              setConfirmingBatch(false);
              onToggleBatchMode();
            }}
          >
            {batchMode ? '完成' : '管理'}
          </Button>
          <Button
            ref={mobileCloseButton}
            type="button"
            size="icon"
            variant="ghost"
            className="size-7 sm:hidden"
            aria-label="关闭会话列表"
            onClick={onCloseMobile}
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <Button
        size="sm"
        className="w-full justify-center gap-1.5"
        disabled={batchMode}
        onClick={onNew}
      >
        <Plus className="size-4" />
        新会话
      </Button>

      <form
        className="relative"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          value={searchDraft}
          onChange={(event) => onSearchDraftChange(event.target.value)}
          placeholder="搜索会话标题"
          aria-label="搜索会话标题"
          className="h-9 w-full rounded-lg border bg-canvas/60 pr-2 pl-8 text-xs outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-brand/30 focus-visible:ring-1 focus-visible:ring-brand/20"
        />
      </form>

      {loading && <p className="px-1 py-2 text-xs text-muted-foreground">加载中…</p>}
      {batchNotice && !error && (
        <p className="px-1 py-1 text-xs text-muted-foreground" aria-live="polite">
          {batchNotice}
        </p>
      )}
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

      <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-0.5">
        {sessions.map((session) => {
          const active = session.session_id === activeSessionId;
          if (batchMode) {
            return (
              <li key={session.session_id}>
                <label
                  className={cn(
                    'flex cursor-pointer items-start gap-2 rounded-xl border bg-canvas/60 p-2.5 text-xs transition-colors',
                    batchSelected.has(session.session_id) && 'border-brand/30 bg-brand/5',
                  )}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 accent-brand"
                    checked={batchSelected.has(session.session_id)}
                    onChange={() => onBatchToggleSelect(session.session_id)}
                    disabled={batchHiding}
                    aria-label={`选择会话 ${session.title ?? '无标题'}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 break-words text-[13px] font-medium">
                      {session.title ?? '无标题'}
                    </span>
                    <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                      <MessageSquare className="size-3" />
                      {session.run_count} 轮 · {formatUpdated(session.updated_at)}
                    </span>
                  </span>
                </label>
              </li>
            );
          }
          if (session.session_id === renamingId) {
            return (
              <li key={session.session_id}>
                <form
                  className="flex flex-col gap-1.5 rounded-xl border bg-panel p-2 shadow-sm"
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
          if (confirmingId === session.session_id) {
            return (
              <li key={session.session_id}>
                <div className="flex flex-col gap-2 rounded-xl border border-danger/30 bg-danger/5 p-2.5">
                  <p className="text-xs leading-5 text-muted-foreground">
                    从列表移除「{session.title ?? '无标题'}」？run 与审批仍按保留期保存。
                  </p>
                  <div className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      type="button"
                      onClick={() => setConfirmingId(null)}
                    >
                      取消
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      type="button"
                      disabled={hidingId === session.session_id}
                      onClick={() => {
                        setConfirmingId(null);
                        onHide(session.session_id);
                      }}
                    >
                      {hidingId === session.session_id ? '移除中…' : '移除'}
                    </Button>
                  </div>
                </div>
              </li>
            );
          }
          return (
            <li key={session.session_id} className="group relative">
              <div
                className={cn(
                  'rounded-xl border border-transparent transition-colors',
                  active ? 'border-brand/20 bg-brand/5' : 'hover:bg-canvas',
                )}
              >
                <button
                  type="button"
                  aria-current={active ? 'true' : undefined}
                  disabled={busy}
                  className="w-full min-w-0 rounded-xl px-3 py-2.5 pr-24 text-left disabled:cursor-default disabled:opacity-60"
                  onClick={() => onSelect(session.session_id)}
                >
                  <span className="flex items-center gap-1.5">
                    {session.pinned && <Pin className="size-3 shrink-0 fill-current text-brand" />}
                    <span className="truncate text-[13px] font-medium">
                      {session.title ?? '无标题'}
                    </span>
                  </span>
                  <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                    <MessageSquare className="size-3" />
                    {session.run_count} 轮<span className="px-0.5">·</span>
                    {formatUpdated(session.updated_at)}
                  </span>
                </button>
                <div
                  className={cn(
                    'absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-0.5 rounded-md bg-panel/95 p-0.5 shadow-sm ring-1 ring-line/60 transition-opacity',
                    active
                      ? 'opacity-100'
                      : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100',
                  )}
                >
                  {session.pinned !== undefined && (
                    <Button
                      size="icon"
                      variant="ghost"
                      className={cn('size-6 text-muted-foreground', session.pinned && 'text-brand')}
                      aria-label={`${session.pinned ? '取消置顶' : '置顶'}会话 ${session.title ?? '无标题'}`}
                      aria-pressed={session.pinned}
                      title={
                        !session.pinned && pinLimitReached
                          ? `置顶数量已达上限（${pinLimit} 个）`
                          : undefined
                      }
                      disabled={busy || pinningId !== null || (!session.pinned && pinLimitReached)}
                      onClick={() => onTogglePin(session)}
                    >
                      <Pin className={cn('size-3.5', session.pinned && 'fill-current')} />
                    </Button>
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-6 text-muted-foreground"
                    aria-label={`重命名会话 ${session.title ?? '无标题'}`}
                    disabled={busy}
                    onClick={() => onRenameStart(session)}
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-6 text-muted-foreground hover:text-danger"
                    aria-label={`从列表移除会话 ${session.title ?? '无标题'}`}
                    disabled={busy || hidingId !== null}
                    onClick={() => setConfirmingId(session.session_id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
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

      {batchMode && (
        <div className="space-y-2 border-t pt-2.5">
          {confirmingBatch ? (
            <div className="space-y-2 rounded-xl border border-danger/30 bg-danger/5 p-2.5">
              <p className="text-xs text-muted-foreground">
                从列表移除选中的 {batchSelected.size} 个会话？run 与审批仍按保留期保存。
              </p>
              <div className="flex justify-end gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  type="button"
                  onClick={() => setConfirmingBatch(false)}
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  type="button"
                  disabled={batchHiding || batchSelected.size === 0}
                  onClick={() => {
                    setConfirmingBatch(false);
                    onHideSelected();
                  }}
                >
                  {batchHiding ? '移除中…' : '确认移除'}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-1">
              <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={allBatchSelected}
                  onChange={onBatchToggleAll}
                  disabled={sessions.length === 0 || batchHiding}
                  aria-label="全选已加载会话"
                />
                全选已加载
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={batchSelected.size === 0 || batchHiding}
                onClick={() => setConfirmingBatch(true)}
              >
                {batchHiding ? '移除中…' : `移除选中（${batchSelected.size}）`}
              </Button>
            </div>
          )}
        </div>
      )}

      <div className="border-t pt-2">
        <Button
          size="sm"
          variant="ghost"
          className="w-full justify-start text-muted-foreground"
          aria-expanded={hiddenOpen}
          aria-controls="hidden-sessions"
          onClick={onToggleHidden}
        >
          {hiddenOpen ? '收起已移除的会话' : '已移除的会话'}
        </Button>
        {hiddenOpen && (
          <div id="hidden-sessions" className="mt-1 max-h-56 space-y-1 overflow-y-auto pr-1">
            <form
              className="flex gap-1"
              onSubmit={(event) => {
                event.preventDefault();
                onHiddenSearch();
              }}
            >
              <input
                value={hiddenDraftQuery}
                onChange={(event) => onHiddenDraftChange(event.target.value)}
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
                  checked={allHiddenSelected}
                  onChange={onHiddenToggleAll}
                  disabled={hiddenSessions.length === 0 || restoringBatch || restoringId !== null}
                  aria-label="全选已加载的已移除会话"
                />
                全选
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={hiddenSelected.size === 0 || restoringBatch || restoringId !== null}
                onClick={onRestoreSelected}
              >
                {restoringBatch ? '恢复中…' : `恢复选中（${hiddenSelected.size}）`}
              </Button>
            </div>
            {hiddenLoading && <p className="px-1 py-1 text-xs text-muted-foreground">加载中…</p>}
            {hiddenError && <p className="px-1 py-1 text-xs text-danger">{hiddenError}</p>}
            {hiddenNotice && (
              <p className="px-1 py-1 text-xs text-muted-foreground" aria-live="polite">
                {hiddenNotice}
              </p>
            )}
            {!hiddenLoading && !hiddenError && hiddenSessions.length === 0 && (
              <p className="px-1 py-1 text-xs text-muted-foreground">
                {hiddenQuery.trim() ? '没有匹配的已移除会话。' : '没有已移除的会话。'}
              </p>
            )}
            {hiddenSessions.map((item) => (
              <div
                key={item.session_id}
                className="flex items-start gap-1.5 rounded-md border bg-canvas p-1.5"
              >
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={hiddenSelected.has(item.session_id)}
                  onChange={() => onHiddenToggleSelect(item.session_id)}
                  aria-label={`选择已移除会话 ${item.title ?? '无标题'}`}
                  disabled={restoringBatch}
                />
                <div className="min-w-0 flex-1">
                  <span className="line-clamp-2 break-words text-xs">{item.title ?? '无标题'}</span>
                  <span className="block text-[11px] text-muted-foreground">
                    {item.run_count} 轮 · 移除于 {formatUpdated(item.hidden_at)}
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
            {hiddenHasMore && (
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                disabled={hiddenLoadingMore || hiddenLoading}
                onClick={onHiddenLoadMore}
              >
                {hiddenLoadingMore ? '加载中…' : '加载更多'}
              </Button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
