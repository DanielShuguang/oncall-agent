import { useCallback, useRef, useState } from 'react';
import { CitationPreviewDialog } from './CitationPreviewDialog';
import { ChatComposer } from './ChatComposer';
import { ChatHeader } from './ChatHeader';
import { ChatMessages } from './ChatMessages';
import { SessionList } from './SessionList';
import { useChat } from './store';
import { useChatHistory } from './useChatHistory';
import { useHiddenSessions } from './useHiddenSessions';
import { useSessionList } from './useSessionList';
import { useSessionMutations } from './useSessionMutations';
import type { Citation } from './types';

export default function ChatPage() {
  const { runtime, sessionId, sending, retry, resolve, abort } = useChat();
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  // 窄屏（<640px）会话栏默认隐藏，用抽屉访问（ADR-0076）。
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const sessionDrawerTrigger = useRef<HTMLButtonElement>(null);
  const closeSessionDrawer = useCallback(() => {
    setSessionDrawerOpen(false);
    // 关闭后把焦点还给触发按钮；抽屉内的焦点陷阱由 SessionList 负责（ADR-0077）。
    if (window.matchMedia('(max-width: 639px)').matches) {
      sessionDrawerTrigger.current?.focus();
    }
  }, []);

  const sessions = useSessionList();
  const history = useChatHistory({
    sessions: sessions.sessions,
    sessionsLoaded: sessions.sessionsLoaded,
    sessionId,
    sending,
    refreshSessions: sessions.refresh,
    resetRename: sessions.resetRename,
    setSessionsError: sessions.setError,
    setActiveCitation,
  });
  const mutations = useSessionMutations({
    sessionId,
    sessions: sessions.sessions,
    batchHideSelected: sessions.batchHideSelected,
    setBatchHideSelected: sessions.setBatchHideSelected,
    refreshSessions: sessions.refresh,
    setSessionsError: sessions.setError,
  });
  const hidden = useHiddenSessions(sessions.refresh);
  const activeSession = sessions.sessions.find((item) => item.session_id === sessionId);

  const hideSession = async (targetSessionId: string) => {
    const result = await mutations.onHideSession(targetSessionId);
    if (!result.ok) return;
    if (result.current) history.onNewSession();
    hidden.reset();
  };

  const hideSelected = async () => {
    const result = await mutations.onHideSelectedSessions();
    if (!result.ok) return;
    if (result.current) history.onNewSession();
    hidden.reset();
  };

  return (
    <div className="flex min-h-0 flex-1 bg-canvas">
      {sessionDrawerOpen && (
        <button
          type="button"
          tabIndex={-1}
          aria-label="关闭会话列表"
          className="fixed inset-0 z-30 touch-none bg-black/30 backdrop-blur-[1px] sm:hidden"
          onClick={closeSessionDrawer}
        />
      )}
      <SessionList
        mobileOpen={sessionDrawerOpen}
        onCloseMobile={closeSessionDrawer}
        sessions={sessions.sessions}
        activeSessionId={sessionId}
        loading={sessions.loading}
        error={sessions.error}
        busy={history.historyLoading}
        hasMore={sessions.cursor !== null}
        loadingMore={sessions.loadingMore}
        query={sessions.query}
        searchDraft={sessions.draftQuery}
        onSearchDraftChange={sessions.setDraftQuery}
        onSearch={sessions.onSearch}
        onSelect={(id) => {
          closeSessionDrawer();
          void history.onSelectSession(id);
        }}
        onNew={() => {
          closeSessionDrawer();
          history.onNewSession();
        }}
        onRetry={() => sessions.refresh()}
        onLoadMore={() => void sessions.loadMore()}
        renamingId={sessions.renamingId}
        renameDraft={sessions.renameDraft}
        renameSaving={sessions.renameSaving}
        onRenameStart={sessions.onRenameStart}
        onRenameDraftChange={sessions.setRenameDraft}
        onRenameSubmit={() => void sessions.onRenameSubmit()}
        onRenameCancel={sessions.onRenameCancel}
        pinningId={sessions.pinningId}
        pinnedCount={sessions.pinnedCount}
        pinLimit={sessions.pinLimit}
        onTogglePin={(item) => void sessions.onTogglePin(item)}
        hidingId={mutations.hidingId}
        onHide={(id) => void hideSession(id)}
        batchMode={mutations.batchHideMode}
        batchSelected={mutations.batchHideSelected}
        batchHiding={mutations.batchHiding}
        batchNotice={mutations.batchHideNotice}
        onToggleBatchMode={mutations.onToggleBatchHide}
        onBatchToggleSelect={mutations.onBatchHideToggleSelect}
        onBatchToggleAll={mutations.onBatchHideToggleAll}
        onHideSelected={() => void hideSelected()}
        hiddenOpen={hidden.hiddenOpen}
        hiddenSessions={hidden.hiddenSessions}
        hiddenLoading={hidden.hiddenLoading}
        hiddenError={hidden.hiddenError}
        hiddenNotice={hidden.hiddenNotice}
        hiddenQuery={hidden.hiddenQuery}
        hiddenDraftQuery={hidden.hiddenDraftQuery}
        hiddenHasMore={hidden.hiddenCursor !== null}
        hiddenLoadingMore={hidden.hiddenLoadingMore}
        onHiddenDraftChange={hidden.setHiddenDraftQuery}
        onHiddenSearch={hidden.onHiddenSearch}
        onHiddenLoadMore={() => void hidden.onHiddenLoadMore()}
        restoringId={hidden.restoringId}
        restoringBatch={hidden.restoringBatch}
        hiddenSelected={hidden.hiddenSelected}
        onHiddenToggleSelect={hidden.onHiddenToggleSelect}
        onHiddenToggleAll={hidden.onHiddenToggleAll}
        onRestoreSelected={() => void hidden.onRestoreSelected()}
        onToggleHidden={() => void hidden.onToggleHidden()}
        onRestore={(id) => void hidden.onRestoreSession(id)}
      />
      <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-panel">
        <ChatHeader
          activeSession={activeSession}
          phase={runtime.phase}
          drawerOpen={sessionDrawerOpen}
          setDrawerOpen={setSessionDrawerOpen}
          triggerRef={sessionDrawerTrigger}
        />
        <ChatMessages
          runtime={runtime}
          sending={sending}
          resolve={resolve}
          onRetry={retry}
          historyCursor={history.historyCursor}
          historyOlderLoading={history.historyOlderLoading}
          onLoadEarlier={() => void history.loadEarlier()}
          onSuggestion={history.setText}
          onCitation={setActiveCitation}
        />
        <CitationPreviewDialog citation={activeCitation} onClose={() => setActiveCitation(null)} />
        <ChatComposer
          text={history.text}
          setText={history.setText}
          sending={sending}
          onSend={() => void history.onSend()}
          abort={abort}
          onNewSession={history.onNewSession}
          phase={runtime.phase}
          historyLoading={history.historyLoading}
          costCents={runtime.costCents}
        />
      </section>
    </div>
  );
}
