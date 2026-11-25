import { useRef, useState } from 'react';
import {
  listHiddenSessions,
  restoreSession,
  restoreSessions,
  type HiddenSession,
} from '@/api/sessions';
import { formatRestoreNotice } from './restoreNotice';

export function useHiddenSessions(refreshSessions: () => void) {
  // 已移除的会话折叠区（ADR-0043）；打开时才拉取，恢复只删 hidden_sessions 行
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const [hiddenSessions, setHiddenSessions] = useState<HiddenSession[]>([]);
  const [hiddenLoading, setHiddenLoading] = useState(false);
  const [hiddenError, setHiddenError] = useState<string | null>(null);
  // 已移除视图的搜索与分页（ADR-0047）：与主列表共用「标题匹配」口径
  const [hiddenQuery, setHiddenQuery] = useState('');
  // 批量恢复期间用户仍可能改搜索词；重拉第一页必须用最新关键词，而不是提交时的闭包值。
  const hiddenQueryRef = useRef(hiddenQuery);
  const [hiddenDraftQuery, setHiddenDraftQuery] = useState('');
  const [hiddenCursor, setHiddenCursor] = useState<string | null>(null);
  const [hiddenLoadingMore, setHiddenLoadingMore] = useState(false);
  //: 首屏同过滤总数（ADR-0134）；后续页不清空，恢复时本地减一
  const [hiddenTotal, setHiddenTotal] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  // 批量恢复（ADR-0049/0055）：一次最多 50 个，部分成功；选中只作用于当前已加载页
  const [hiddenSelected, setHiddenSelected] = useState<Set<string>>(new Set());
  const [restoringBatch, setRestoringBatch] = useState(false);
  const [hiddenNotice, setHiddenNotice] = useState<string | null>(null);
  // 快速收起/展开时旧请求可能晚于新请求返回：只接受最后一次展开的结果。
  const hiddenRequest = useRef(0);

  // 搜索词变化时同步 ref，供批量恢复后重拉第一页使用。
  const updateHiddenQuery = (value: string) => {
    setHiddenQuery(value);
    hiddenQueryRef.current = value;
  };

  const reset = () => {
    hiddenRequest.current += 1;
    setHiddenOpen(false);
    setHiddenLoading(false);
    setHiddenLoadingMore(false);
    setHiddenSessions([]);
    setHiddenCursor(null);
    setHiddenTotal(null);
    setHiddenSelected(new Set());
    updateHiddenQuery('');
    setHiddenDraftQuery('');
    setHiddenNotice(null);
  };

  const loadFirstPage = async (query: string) => {
    const requestId = ++hiddenRequest.current;
    setHiddenLoading(true);
    setHiddenLoadingMore(false);
    setHiddenError(null);
    try {
      const page = await listHiddenSessions(50, null, query || null);
      if (requestId === hiddenRequest.current) {
        setHiddenSessions(page.items);
        setHiddenCursor(page.next_cursor);
        setHiddenTotal(page.total ?? null);
      }
    } catch (err) {
      if (requestId === hiddenRequest.current) {
        setHiddenError(err instanceof Error ? err.message : '已移除会话加载失败');
      }
    } finally {
      if (requestId === hiddenRequest.current) setHiddenLoading(false);
    }
  };

  const onToggleHidden = async () => {
    if (hiddenOpen) {
      hiddenRequest.current += 1;
      setHiddenOpen(false);
      setHiddenLoading(false);
      setHiddenLoadingMore(false);
      setHiddenSelected(new Set());
      setHiddenNotice(null);
      return;
    }
    setHiddenOpen(true);
    setHiddenNotice(null);
    await loadFirstPage(hiddenQuery);
  };

  const onHiddenSearch = () => {
    const nextQuery = hiddenDraftQuery.trim();
    updateHiddenQuery(nextQuery);
    setHiddenCursor(null);
    setHiddenTotal(null);
    setHiddenSelected(new Set());
    setHiddenNotice(null);
    void loadFirstPage(nextQuery);
  };

  const onHiddenLoadMore = async () => {
    if (!hiddenCursor || hiddenLoading || hiddenLoadingMore) return;
    const requestId = ++hiddenRequest.current;
    setHiddenLoadingMore(true);
    setHiddenError(null);
    try {
      const page = await listHiddenSessions(50, hiddenCursor, hiddenQuery || null);
      if (requestId === hiddenRequest.current) {
        setHiddenSessions((prev) => [...prev, ...page.items]);
        setHiddenCursor(page.next_cursor);
      }
    } catch (err) {
      if (requestId === hiddenRequest.current) {
        setHiddenError(err instanceof Error ? err.message : '已移除会话加载失败');
      }
    } finally {
      if (requestId === hiddenRequest.current) setHiddenLoadingMore(false);
    }
  };

  const onRestoreSession = async (targetSessionId: string) => {
    if (restoringId) return;
    setRestoringId(targetSessionId);
    setHiddenError(null);
    setHiddenNotice(null);
    try {
      await restoreSession(targetSessionId);
      // 恢复也是列表变更：让在途的已移除请求失效，避免旧页把刚恢复的会话写回来（ADR-0047）。
      hiddenRequest.current += 1;
      setHiddenLoading(false);
      setHiddenLoadingMore(false);
      setHiddenSessions((prev) => prev.filter((item) => item.session_id !== targetSessionId));
      setHiddenTotal((prev) => (prev === null ? null : Math.max(0, prev - 1)));
      setHiddenSelected((prev) => {
        const next = new Set(prev);
        next.delete(targetSessionId);
        return next;
      });
      refreshSessions();
    } catch (err) {
      setHiddenError(err instanceof Error ? err.message : '会话恢复失败');
    } finally {
      setRestoringId(null);
    }
  };

  const onHiddenToggleSelect = (targetSessionId: string) => {
    setHiddenSelected((prev) => {
      const next = new Set(prev);
      if (next.has(targetSessionId)) next.delete(targetSessionId);
      else next.add(targetSessionId);
      return next;
    });
  };

  const onHiddenToggleAll = () => {
    setHiddenSelected((prev) => {
      const allSelected =
        hiddenSessions.length > 0 && hiddenSessions.every((item) => prev.has(item.session_id));
      return allSelected ? new Set() : new Set(hiddenSessions.map((item) => item.session_id));
    });
  };

  const onRestoreSelected = async () => {
    if (restoringBatch || restoringId !== null || hiddenSelected.size === 0) return;
    setRestoringBatch(true);
    setHiddenError(null);
    setHiddenNotice(null);
    try {
      const result = await restoreSessions([...hiddenSelected]);
      setHiddenNotice(formatRestoreNotice(result.restored, result.items));
      // 批量恢复同样让在途请求失效，并从服务端重新拉一页，避免部分成功时本地列表撒谎。
      hiddenRequest.current += 1;
      setHiddenLoading(false);
      setHiddenLoadingMore(false);
      setHiddenSelected(new Set());
      refreshSessions();
      await loadFirstPage(hiddenQueryRef.current);
    } catch (err) {
      setHiddenError(err instanceof Error ? err.message : '批量恢复失败');
    } finally {
      setRestoringBatch(false);
    }
  };

  return {
    hiddenOpen,
    hiddenSessions,
    hiddenLoading,
    hiddenError,
    hiddenQuery,
    hiddenDraftQuery,
    setHiddenDraftQuery,
    hiddenCursor,
    hiddenLoadingMore,
    hiddenTotal,
    restoringId,
    hiddenSelected,
    restoringBatch,
    hiddenNotice,
    reset,
    onToggleHidden,
    onHiddenSearch,
    onHiddenLoadMore,
    onRestoreSession,
    onHiddenToggleSelect,
    onHiddenToggleAll,
    onRestoreSelected,
  };
}
