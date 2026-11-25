/** 会话侧栏（ADR-0030）：只展示服务端投影，不在浏览器本地缓存会话。 */

import { useEffect, useRef, useState, type TouchEvent } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from 'cn';
import { isDrawerSwipeClose } from './drawerSwipe';
import { pinLimitOverflow } from './pinLimit';
import { nextFocusTarget } from './focusTrap';
import type { SessionListProps } from './SessionList.types';
import { HiddenSessionsPanel } from './HiddenSessionsPanel';
import { SessionBatchBar } from './SessionBatchBar';
import { SessionListChrome } from './SessionListChrome';
import { SessionListItem } from './SessionListItem';

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
  const mobileAside = useRef<HTMLElement>(null);
  const mobileCloseButton = useRef<HTMLButtonElement>(null);
  const mobileSearchInput = useRef<HTMLInputElement>(null);
  // 左滑关闭只在松手时判定总位移，不做跟手动画（ADR-0104）。
  const drawerTouchStart = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    const media = window.matchMedia('(max-width: 639px)');
    const onResize = (event: MediaQueryListEvent) => {
      if (event.matches) return;
      // 变宽后 X 会被 sm:hidden 隐藏，先把焦点放到可见的搜索框，再关闭抽屉。
      mobileSearchInput.current?.focus();
      onCloseMobile();
    };
    media.addEventListener('change', onResize);
    if (!media.matches) {
      onCloseMobile();
      return () => media.removeEventListener('change', onResize);
    }
    // 打开时焦点进入抽屉，关闭时由 ChatPage 还给菜单按钮（ADR-0076/0077）。
    mobileCloseButton.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseMobile();
        return;
      }
      if (event.key !== 'Tab') return;
      const container = mobileAside.current;
      if (!container) return;
      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const target = nextFocusTarget(focusable, document.activeElement, event.shiftKey);
      if (target) {
        event.preventDefault();
        target.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      media.removeEventListener('change', onResize);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [mobileOpen, onCloseMobile]);
  const onDrawerTouchStart = (event: TouchEvent<HTMLElement>) => {
    if (!mobileOpen || event.touches.length !== 1) {
      drawerTouchStart.current = null;
      return;
    }
    // 从输入/下拉/可编辑元素起手时，横向拖动通常是选词或控件手势，不应当关闭抽屉。
    const target = event.target;
    if (
      target instanceof Element &&
      target.closest('input, textarea, select, [contenteditable="true"]')
    ) {
      drawerTouchStart.current = null;
      return;
    }
    const touch = event.touches[0];
    if (!touch) return;
    drawerTouchStart.current = { x: touch.clientX, y: touch.clientY };
  };
  const onDrawerTouchEnd = (event: TouchEvent<HTMLElement>) => {
    const start = drawerTouchStart.current;
    drawerTouchStart.current = null;
    if (!start || !mobileOpen) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    if (isDrawerSwipeClose(touch.clientX - start.x, touch.clientY - start.y)) {
      onCloseMobile();
    }
  };
  const onDrawerTouchCancel = () => {
    drawerTouchStart.current = null;
  };
  const allBatchSelected =
    sessions.length > 0 && sessions.every((item) => batchSelected.has(item.session_id));
  const pinLimitReached = pinnedCount !== null && pinLimit !== null && pinnedCount >= pinLimit;
  const pinOverflow = pinLimitOverflow(pinnedCount, pinLimit);
  const allHiddenSelected =
    hiddenSessions.length > 0 &&
    hiddenSessions.every((item) => hiddenSelected.has(item.session_id));

  return (
    <aside
      ref={mobileAside}
      id="session-list"
      role={mobileOpen ? 'dialog' : undefined}
      aria-label="会话列表"
      aria-modal={mobileOpen || undefined}
      onTouchStart={onDrawerTouchStart}
      onTouchEnd={onDrawerTouchEnd}
      onTouchCancel={onDrawerTouchCancel}
      className={cn(
        'w-72 shrink-0 flex-col gap-3 border-r bg-panel p-3 overscroll-contain',
        mobileOpen
          ? 'fixed inset-y-0 left-0 z-40 flex shadow-xl sm:static sm:z-auto sm:shadow-none'
          : 'hidden sm:flex',
      )}
    >
      <SessionListChrome
        closeButtonRef={mobileCloseButton}
        searchInputRef={mobileSearchInput}
        batchMode={batchMode}
        onToggleBatchMode={() => {
          setConfirmingBatch(false);
          onToggleBatchMode();
        }}
        onNew={onNew}
        onCloseMobile={onCloseMobile}
        searchDraft={searchDraft}
        onSearchDraftChange={onSearchDraftChange}
        onSearch={onSearch}
        loading={loading}
        error={error}
        query={query}
        sessionCount={sessions.length}
        batchNotice={batchNotice}
        pinOverflow={pinOverflow}
        onRetry={onRetry}
      />

      <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-0.5">
        {sessions.map((session) => (
          <li key={session.session_id}>
            <SessionListItem
              session={session}
              active={session.session_id === activeSessionId}
              batchMode={batchMode}
              batchSelected={batchSelected.has(session.session_id)}
              batchHiding={batchHiding}
              busy={busy}
              renaming={session.session_id === renamingId}
              renameDraft={renameDraft}
              renameSaving={renameSaving}
              confirming={confirmingId === session.session_id}
              hidingId={hidingId}
              pinningId={pinningId}
              pinLimitReached={pinLimitReached}
              pinLimit={pinLimit}
              onBatchToggleSelect={onBatchToggleSelect}
              onSelect={() => onSelect(session.session_id)}
              onTogglePin={() => onTogglePin(session)}
              onRenameStart={() => onRenameStart(session)}
              onRenameDraftChange={onRenameDraftChange}
              onRenameSubmit={onRenameSubmit}
              onRenameCancel={onRenameCancel}
              onConfirmRemove={() => setConfirmingId(session.session_id)}
              onCancelRemove={() => setConfirmingId(null)}
              onHide={() => {
                setConfirmingId(null);
                onHide(session.session_id);
              }}
            />
          </li>
        ))}
      </ul>

      {hasMore && (
        <Button size="sm" variant="outline" disabled={loadingMore || busy} onClick={onLoadMore}>
          {loadingMore ? '加载中…' : '加载更多会话'}
        </Button>
      )}

      <SessionBatchBar
        mode={batchMode}
        hiding={batchHiding}
        selectedCount={batchSelected.size}
        sessionsCount={sessions.length}
        confirming={confirmingBatch}
        allSelected={allBatchSelected}
        onToggleAll={onBatchToggleAll}
        onConfirm={() => setConfirmingBatch(true)}
        onCancel={() => setConfirmingBatch(false)}
        onHideSelected={onHideSelected}
      />

      <HiddenSessionsPanel
        open={hiddenOpen}
        sessions={hiddenSessions}
        loading={hiddenLoading}
        error={hiddenError}
        notice={hiddenNotice}
        query={hiddenQuery}
        draftQuery={hiddenDraftQuery}
        hasMore={hiddenHasMore}
        loadingMore={hiddenLoadingMore}
        restoringId={restoringId}
        restoringBatch={restoringBatch}
        selected={hiddenSelected}
        allSelected={allHiddenSelected}
        onToggle={onToggleHidden}
        onDraftChange={onHiddenDraftChange}
        onSearch={onHiddenSearch}
        onLoadMore={onHiddenLoadMore}
        onToggleSelect={onHiddenToggleSelect}
        onToggleAll={onHiddenToggleAll}
        onRestoreSelected={onRestoreSelected}
        onRestore={onRestore}
      />
    </aside>
  );
}
