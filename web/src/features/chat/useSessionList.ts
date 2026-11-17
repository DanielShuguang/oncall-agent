import { useEffect, useRef, useState } from 'react';
import {
  listSessions,
  pinSession,
  renameSession,
  unpinSession,
  type SessionSummary,
} from '@/api/sessions';

export function useSessionList() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pinnedCount, setPinnedCount] = useState<number | null>(null);
  const [pinLimit, setPinLimit] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [draftQuery, setDraftQuery] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const [renameSaving, setRenameSaving] = useState(false);
  const [pinningId, setPinningId] = useState<string | null>(null);
  const renameRequest = useRef(0);
  // 刷新会替换整个会话列表：加载更多/初始加载的旧页回来时不能 append 到新列表上。
  const sessionsRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++sessionsRequest.current;
    listSessions(20)
      .then((page) => {
        if (!cancelled && requestId === sessionsRequest.current) {
          setSessions(page.items);
          setCursor(page.next_cursor);
          setPinnedCount(page.pinned_count ?? null);
          setPinLimit(page.pin_limit ?? null);
          setSessionsLoaded(true);
        }
        return page.items;
      })
      .catch((err: unknown) => {
        if (!cancelled && requestId === sessionsRequest.current) {
          setError(err instanceof Error ? err.message : '会话列表加载失败');
          setSessionsLoaded(true);
        }
      })
      .finally(() => {
        if (!cancelled && requestId === sessionsRequest.current) setLoading(false);
      });
    return () => {
      cancelled = true;
      sessionsRequest.current += 1;
    };
  }, []);

  const refresh = (nextQuery: string = query) => {
    const requestId = ++sessionsRequest.current;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    void listSessions(20, null, nextQuery || null)
      .then((page) => {
        if (requestId === sessionsRequest.current) {
          setSessions(page.items);
          setCursor(page.next_cursor);
          setPinnedCount(page.pinned_count ?? null);
          setPinLimit(page.pin_limit ?? null);
          setSessionsLoaded(true);
        }
        return page.items;
      })
      .catch((err: unknown) => {
        if (requestId === sessionsRequest.current) {
          setError(err instanceof Error ? err.message : '会话列表加载失败');
        }
      })
      .finally(() => {
        if (requestId === sessionsRequest.current) setLoading(false);
      });
  };

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = sessionsRequest.current;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await listSessions(20, cursor, query || null);
      if (requestId !== sessionsRequest.current) return;
      setSessions((prev) => [...prev, ...page.items]);
      setCursor(page.next_cursor);
      setPinnedCount(page.pinned_count ?? null);
      setPinLimit(page.pin_limit ?? null);
    } catch (err) {
      if (requestId === sessionsRequest.current) {
        setError(err instanceof Error ? err.message : '更多会话加载失败');
      }
    } finally {
      if (requestId === sessionsRequest.current) setLoadingMore(false);
    }
  };

  const onSearch = () => {
    const next = draftQuery.trim();
    setQuery(next);
    refresh(next);
  };

  const resetRename = () => {
    renameRequest.current += 1;
    setRenameSaving(false);
    setRenamingId(null);
    setRenameDraft('');
  };

  const onRenameStart = (session: SessionSummary) => {
    renameRequest.current += 1;
    setRenameSaving(false);
    setRenamingId(session.session_id);
    setRenameDraft(session.title ?? '');
  };

  const onRenameCancel = () => {
    resetRename();
  };

  const onRenameSubmit = async () => {
    if (!renamingId || renameSaving) return;
    const title = renameDraft.trim();
    if (title.length > 60) {
      setError('标题最多 60 个字符');
      return;
    }
    const requestId = ++renameRequest.current;
    setRenameSaving(true);
    setError(null);
    try {
      // 留空 = 恢复默认标题（首条问题）
      await renameSession(renamingId, title || null);
      refresh();
      if (requestId === renameRequest.current) {
        setRenamingId(null);
        setRenameDraft('');
      }
    } catch (err) {
      if (requestId === renameRequest.current) {
        setError(err instanceof Error ? err.message : '会话重命名失败');
      }
    } finally {
      if (requestId === renameRequest.current) setRenameSaving(false);
    }
  };

  const onTogglePin = async (session: SessionSummary) => {
    if (pinningId || session.pinned === undefined) return;
    setPinningId(session.session_id);
    setError(null);
    try {
      if (session.pinned) await unpinSession(session.session_id);
      else await pinSession(session.session_id);
      // 排序变化：回到第一页重新拉，避免当前页仍按旧顺序排列。
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '置顶操作失败');
    } finally {
      setPinningId(null);
    }
  };

  return {
    sessions,
    sessionsLoaded,
    cursor,
    pinnedCount,
    pinLimit,
    loading,
    loadingMore,
    error,
    query,
    draftQuery,
    setDraftQuery,
    renamingId,
    renameDraft,
    renameSaving,
    pinningId,
    setRenameDraft,
    setError,
    refresh,
    loadMore,
    onSearch,
    onRenameStart,
    onRenameCancel,
    onRenameSubmit,
    resetRename,
    onTogglePin,
  };
}
