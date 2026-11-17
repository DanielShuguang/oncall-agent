import { useEffect, useRef, useState } from 'react';
import { getSessionRuns, type SessionSummary } from '@/api/sessions';
import { transcriptMessages } from './history';
import { clearLastSession, readLastSession, writeLastSession } from './lastSession';
import { useChat } from './store';
import type { Citation } from './types';

interface Args {
  sessions: SessionSummary[];
  sessionsLoaded: boolean;
  sessionId: string | null;
  sending: boolean;
  refreshSessions: () => void;
  resetRename: () => void;
  setSessionsError: (message: string | null) => void;
  setActiveCitation: (citation: Citation | null) => void;
}

export function useChatHistory({
  sessions,
  sessionsLoaded,
  sessionId,
  sending,
  refreshSessions,
  resetRename,
  setSessionsError,
  setActiveCitation,
}: Args) {
  const { send, switchSession, prependHistory, reset } = useChat();
  const [text, setText] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  // 当前会话内更早轮次的 keyset 游标；null 表示没有更早的页（ADR-0033）
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyOlderLoading, setHistoryOlderLoading] = useState(false);
  // 历史会话请求可能乱序返回（连点两个会话、加载中又点了新会话）：
  // 用自增 token 只接受最后一次请求的结果，避免旧的响应把界面切回去。
  const historyRequest = useRef(0);
  // 首屏只尝试恢复一次上次会话；避免列表刷新后反复覆盖用户当前选择。
  const lastSessionRestored = useRef(false);
  // 用户已主动打开/新建会话时，首屏迟到的列表响应不能再自动恢复上次会话。
  const sessionSelectionStarted = useRef(false);
  // 自动恢复占用 historyLoading 时仍允许用户改选其他会话：用户操作优先，旧恢复响应按 token 丢弃。
  const lastSessionRestoring = useRef(false);

  useEffect(() => {
    if (sessionId) writeLastSession(sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionsLoaded || lastSessionRestored.current) return;
    lastSessionRestored.current = true;
    const last = readLastSession();
    if (
      !last ||
      sessionId ||
      sending ||
      sessionSelectionStarted.current ||
      !sessions.some((item) => item.session_id === last)
    ) {
      return;
    }
    const historyId = ++historyRequest.current;
    lastSessionRestoring.current = true;
    setHistoryLoading(true);
    void getSessionRuns(last, 20)
      .then((history) => {
        if (historyId !== historyRequest.current) return undefined;
        setActiveCitation(null);
        setText('');
        resetRename();
        setHistoryCursor(history.next_cursor);
        switchSession(last, transcriptMessages(history.items));
        return undefined;
      })
      .catch((err: unknown) => {
        if (historyId === historyRequest.current) {
          setSessionsError(err instanceof Error ? err.message : '上次会话加载失败');
        }
      })
      .finally(() => {
        lastSessionRestoring.current = false;
        if (historyId === historyRequest.current) setHistoryLoading(false);
      });
  }, [
    resetRename,
    sending,
    sessionId,
    sessions,
    sessionsLoaded,
    setActiveCitation,
    setSessionsError,
    switchSession,
  ]);

  const onSend = async () => {
    const value = text.trim();
    if (!value) return;
    // 发送本身会占用当前会话：首屏迟到的上一次会话恢复不能把本轮运行切走。
    sessionSelectionStarted.current = true;
    lastSessionRestoring.current = false;
    // 发送会沿用当前会话：取消还在路上的历史会话切换，避免它回来后把本轮 UI 覆盖掉
    historyRequest.current += 1;
    setHistoryLoading(false);
    setHistoryOlderLoading(false);
    setText('');
    await send(value);
    refreshSessions();
  };

  const onSelectSession = async (nextSessionId: string) => {
    // 自动恢复在跑时也允许用户改选；此时递增 historyRequest 会让旧恢复响应失效。
    if (sending || (historyLoading && !lastSessionRestoring.current) || nextSessionId === sessionId)
      return;
    sessionSelectionStarted.current = true;
    lastSessionRestoring.current = false;
    const requestId = ++historyRequest.current;
    setHistoryLoading(true);
    setHistoryOlderLoading(false);
    setSessionsError(null);
    try {
      const page = await getSessionRuns(nextSessionId, 20);
      if (requestId !== historyRequest.current) return;
      setActiveCitation(null);
      setText('');
      resetRename();
      setHistoryCursor(page.next_cursor);
      switchSession(nextSessionId, transcriptMessages(page.items));
    } catch (err) {
      if (requestId === historyRequest.current) {
        setSessionsError(err instanceof Error ? err.message : '历史会话加载失败');
      }
    } finally {
      if (requestId === historyRequest.current) setHistoryLoading(false);
    }
  };

  const loadEarlier = async () => {
    if (!sessionId || !historyCursor || historyOlderLoading || historyLoading || sending) return;
    const requestId = historyRequest.current;
    setHistoryOlderLoading(true);
    setSessionsError(null);
    try {
      const page = await getSessionRuns(sessionId, 20, historyCursor);
      if (requestId !== historyRequest.current) return;
      prependHistory(transcriptMessages(page.items));
      setHistoryCursor(page.next_cursor);
    } catch (err) {
      if (requestId === historyRequest.current) {
        setSessionsError(err instanceof Error ? err.message : '更早的对话加载失败');
      }
    } finally {
      if (requestId === historyRequest.current) setHistoryOlderLoading(false);
    }
  };

  const onNewSession = () => {
    sessionSelectionStarted.current = true;
    lastSessionRestoring.current = false;
    clearLastSession();
    historyRequest.current += 1;
    setHistoryLoading(false);
    setHistoryOlderLoading(false);
    setHistoryCursor(null);
    resetRename();
    setActiveCitation(null);
    setText('');
    reset();
  };

  return {
    text,
    setText,
    historyLoading,
    historyCursor,
    historyOlderLoading,
    onSend,
    onSelectSession,
    loadEarlier,
    onNewSession,
  };
}
