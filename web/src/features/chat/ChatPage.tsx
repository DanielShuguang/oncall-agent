import { useEffect, useRef, useState } from 'react';
import { cn } from 'cn';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

import {
  getSessionRuns,
  hideSession,
  listHiddenSessions,
  listSessions,
  renameSession,
  restoreSession,
  type HiddenSession,
  type SessionSummary,
} from '@/api/sessions';
import { CitationPreviewDialog } from './CitationPreviewDialog';
import { SessionList } from './SessionList';
import { Timeline } from './Timeline';
import { transcriptMessages } from './history';
import { useChat } from './store';
import type { Citation } from './types';

const PHASE_LABEL: Record<string, string> = {
  idle: '就绪',
  running: '执行中',
  awaiting_approval: '等待审批',
  completed: '已完成',
  failed: '失败',
  interrupted: '已中断',
};

export default function ChatPage() {
  const {
    runtime,
    sessionId,
    sending,
    send,
    retry,
    resolve,
    abort,
    reset,
    switchSession,
    prependHistory,
  } = useChat();
  const [text, setText] = useState('');
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsCursor, setSessionsCursor] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  // 已提交的标题搜索词；空串表示不过滤（ADR-0039）
  const [sessionQuery, setSessionQuery] = useState('');
  const [sessionDraftQuery, setSessionDraftQuery] = useState('');
  // 行内改会话标题（ADR-0040）；renamingId 一次只允许一个
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  // 重命名请求可能晚于下一次编辑返回：token 变了就不要再关掉新的编辑器。
  const [renameSaving, setRenameSaving] = useState(false);
  const renameRequest = useRef(0);
  // 正在从会话列表移除的会话（ADR-0041）；移除只影响列表，不删 run
  const [hidingId, setHidingId] = useState<string | null>(null);
  // 已移除的会话折叠区（ADR-0043）；打开时才拉取，恢复只删 hidden_sessions 行
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const [hiddenSessions, setHiddenSessions] = useState<HiddenSession[]>([]);
  const [hiddenLoading, setHiddenLoading] = useState(false);
  const [hiddenError, setHiddenError] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  // 当前会话内更早轮次的 keyset 游标；null 表示没有更早的页（ADR-0033）
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyOlderLoading, setHistoryOlderLoading] = useState(false);
  // 历史会话请求可能乱序返回（连点两个会话、加载中又点了新会话）：
  // 用自增 token 只接受最后一次请求的结果，避免旧的响应把界面切回去。
  const historyRequest = useRef(0);
  // 刷新会替换整个会话列表：加载更多/初始加载的旧页回来时不能 append 到新列表上。
  const sessionsRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++sessionsRequest.current;
    listSessions(20)
      .then((page) => {
        if (!cancelled && requestId === sessionsRequest.current) {
          setSessions(page.items);
          setSessionsCursor(page.next_cursor);
        }
        return page.items;
      })
      .catch((err: unknown) => {
        if (!cancelled && requestId === sessionsRequest.current) {
          setSessionsError(err instanceof Error ? err.message : '会话列表加载失败');
        }
      })
      .finally(() => {
        if (!cancelled && requestId === sessionsRequest.current) setSessionsLoading(false);
      });
    return () => {
      cancelled = true;
      historyRequest.current += 1;
      sessionsRequest.current += 1;
    };
  }, []);

  const refreshSessions = (query: string = sessionQuery) => {
    const requestId = ++sessionsRequest.current;
    setSessionsLoading(true);
    setSessionsLoadingMore(false);
    setSessionsError(null);
    listSessions(20, null, query || null)
      .then((page) => {
        if (requestId !== sessionsRequest.current) return page.items;
        setSessions(page.items);
        setSessionsCursor(page.next_cursor);
        return page.items;
      })
      .catch((err: unknown) => {
        if (requestId === sessionsRequest.current) {
          setSessionsError(err instanceof Error ? err.message : '会话列表加载失败');
        }
      })
      .finally(() => {
        if (requestId === sessionsRequest.current) setSessionsLoading(false);
      });
  };

  const loadMoreSessions = async () => {
    if (!sessionsCursor || sessionsLoadingMore) return;
    const requestId = sessionsRequest.current;
    setSessionsLoadingMore(true);
    setSessionsError(null);
    try {
      const page = await listSessions(20, sessionsCursor, sessionQuery || null);
      if (requestId !== sessionsRequest.current) return;
      setSessions((prev) => [...prev, ...page.items]);
      setSessionsCursor(page.next_cursor);
    } catch (err) {
      if (requestId === sessionsRequest.current) {
        setSessionsError(err instanceof Error ? err.message : '更多会话加载失败');
      }
    } finally {
      if (requestId === sessionsRequest.current) setSessionsLoadingMore(false);
    }
  };

  const onSearchSessions = () => {
    const next = sessionDraftQuery.trim();
    setSessionQuery(next);
    refreshSessions(next);
  };

  const onRenameStart = (session: SessionSummary) => {
    renameRequest.current += 1;
    setRenameSaving(false);
    setRenamingId(session.session_id);
    setRenameDraft(session.title ?? '');
  };

  const onRenameCancel = () => {
    renameRequest.current += 1;
    setRenameSaving(false);
    setRenamingId(null);
    setRenameDraft('');
  };

  const onRenameSubmit = async () => {
    if (!renamingId || renameSaving) return;
    const title = renameDraft.trim();
    if (title.length > 60) {
      setSessionsError('标题最多 60 个字符');
      return;
    }
    const requestId = ++renameRequest.current;
    setRenameSaving(true);
    setSessionsError(null);
    try {
      // 留空 = 恢复默认标题（首条问题）
      await renameSession(renamingId, title || null);
      refreshSessions();
      if (requestId === renameRequest.current) {
        setRenamingId(null);
        setRenameDraft('');
      }
    } catch (err) {
      if (requestId === renameRequest.current) {
        setSessionsError(err instanceof Error ? err.message : '会话重命名失败');
      }
    } finally {
      if (requestId === renameRequest.current) setRenameSaving(false);
    }
  };

  const onSend = async () => {
    const value = text.trim();
    if (!value) return;
    // 发送会沿用当前会话：取消还在路上的历史会话切换，避免它回来后把本轮 UI 覆盖掉
    historyRequest.current += 1;
    setHistoryLoading(false);
    setHistoryOlderLoading(false);
    setText('');
    await send(value);
    refreshSessions();
  };

  const onSelectSession = async (nextSessionId: string) => {
    if (sending || historyLoading || nextSessionId === sessionId) return;
    const requestId = ++historyRequest.current;
    setHistoryLoading(true);
    setHistoryOlderLoading(false);
    setSessionsError(null);
    try {
      const page = await getSessionRuns(nextSessionId, 20);
      if (requestId !== historyRequest.current) return;
      setActiveCitation(null);
      setText('');
      renameRequest.current += 1;
      setRenameSaving(false);
      setRenamingId(null);
      setRenameDraft('');
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
    if (!historyCursor || historyOlderLoading || historyLoading || sending) return;
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
    historyRequest.current += 1;
    renameRequest.current += 1;
    setHistoryLoading(false);
    setHistoryOlderLoading(false);
    setHistoryCursor(null);
    setRenameSaving(false);
    setRenamingId(null);
    setRenameDraft('');
    setActiveCitation(null);
    setText('');
    reset();
  };

  const onHideSession = async (targetSessionId: string) => {
    if (hidingId) return;
    setHidingId(targetSessionId);
    setSessionsError(null);
    try {
      await hideSession(targetSessionId);
      if (targetSessionId === sessionId) onNewSession();
      refreshSessions();
      // 列表已经变化，已移除折叠区下次打开时重新拉取。
      setHiddenOpen(false);
      setHiddenSessions([]);
    } catch (err) {
      setSessionsError(err instanceof Error ? err.message : '会话移除失败');
    } finally {
      setHidingId(null);
    }
  };

  const onToggleHiddenSessions = async () => {
    if (hiddenOpen) {
      setHiddenOpen(false);
      return;
    }
    setHiddenOpen(true);
    setHiddenLoading(true);
    setHiddenError(null);
    try {
      setHiddenSessions(await listHiddenSessions(50));
    } catch (err) {
      setHiddenError(err instanceof Error ? err.message : '已移除会话加载失败');
    } finally {
      setHiddenLoading(false);
    }
  };

  const onRestoreSession = async (targetSessionId: string) => {
    if (restoringId) return;
    setRestoringId(targetSessionId);
    setHiddenError(null);
    try {
      await restoreSession(targetSessionId);
      setHiddenSessions((prev) => prev.filter((item) => item.session_id !== targetSessionId));
      refreshSessions();
    } catch (err) {
      setHiddenError(err instanceof Error ? err.message : '会话恢复失败');
    } finally {
      setRestoringId(null);
    }
  };

  return (
    <div className="flex min-h-0 flex-1">
      <SessionList
        sessions={sessions}
        activeSessionId={sessionId}
        loading={sessionsLoading}
        error={sessionsError}
        busy={historyLoading}
        hasMore={sessionsCursor !== null}
        loadingMore={sessionsLoadingMore}
        query={sessionQuery}
        searchDraft={sessionDraftQuery}
        onSearchDraftChange={setSessionDraftQuery}
        onSearch={onSearchSessions}
        onSelect={(id) => void onSelectSession(id)}
        onNew={onNewSession}
        onRetry={() => refreshSessions()}
        onLoadMore={() => void loadMoreSessions()}
        renamingId={renamingId}
        renameDraft={renameDraft}
        renameSaving={renameSaving}
        onRenameStart={onRenameStart}
        onRenameDraftChange={setRenameDraft}
        onRenameSubmit={() => void onRenameSubmit()}
        onRenameCancel={onRenameCancel}
        hidingId={hidingId}
        onHide={(id) => void onHideSession(id)}
        hiddenOpen={hiddenOpen}
        hiddenSessions={hiddenSessions}
        hiddenLoading={hiddenLoading}
        hiddenError={hiddenError}
        restoringId={restoringId}
        onToggleHidden={() => void onToggleHiddenSessions()}
        onRestore={(id) => void onRestoreSession(id)}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        <div aria-live="polite" className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
          {historyCursor && (
            <div className="flex justify-center">
              <Button
                size="sm"
                variant="outline"
                disabled={historyOlderLoading}
                onClick={() => void loadEarlier()}
              >
                {historyOlderLoading ? '加载中…' : '加载更早的对话'}
              </Button>
            </div>
          )}
          {runtime.messages.length === 0 && (
            <Card className="gap-0 py-0">
              <CardContent className="p-3 text-sm">
                试试：「VPN 连不上怎么办」　或　「我电脑连不上打印机了」
              </CardContent>
            </Card>
          )}

          {runtime.steps.map((step) => (
            <div
              key={step.seq ?? `${step.node}-${step.title}`}
              className="flex items-center gap-2 text-xs text-muted-foreground"
            >
              <Badge
                variant="outline"
                className={cn(
                  step.status === 'done' ? 'border-ok/40 text-ok' : 'border-brand/40 text-brand',
                )}
              >
                {step.status === 'done' ? '完成' : '进行'}
              </Badge>
              <span>
                {step.title}
                {step.summary ? ` · ${step.summary}` : ''}
              </span>
            </div>
          ))}

          {runtime.tools.map((tool) => (
            <Card
              key={tool.callId}
              className={cn('gap-0 py-0', tool.write ? 'border-warn/40 bg-warn/5' : 'bg-canvas/50')}
            >
              <CardContent className="p-3">
                <div className="flex items-center gap-2">
                  <Badge variant={tool.write ? 'destructive' : 'secondary'}>{tool.tool}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {tool.status}
                    {tool.durationMs ? ` · ${tool.durationMs}ms` : ''}
                    {tool.attempts && tool.attempts > 1 ? ` · 重试${tool.attempts - 1}次` : ''}
                  </span>
                </div>
                <div className="mt-2 text-[11px] text-muted-foreground">参数</div>
                <pre className="mt-1 max-h-48 overflow-auto rounded-md border bg-panel p-2 font-mono text-xs whitespace-pre-wrap">
                  {JSON.stringify(tool.args, null, 2)}
                </pre>
                {tool.result !== undefined && (
                  <>
                    <div className="mt-2 text-[11px] text-muted-foreground">结果</div>
                    <pre className="mt-1 max-h-64 overflow-auto rounded-md border bg-panel p-2 font-mono text-xs whitespace-pre-wrap">
                      {JSON.stringify(tool.result, null, 2)}
                    </pre>
                  </>
                )}
                {tool.error && <div className="mt-1 text-sm text-destructive">{tool.error}</div>}
              </CardContent>
            </Card>
          ))}

          {runtime.approval && (
            <Card className="gap-0 border-warn/40 bg-warn/5 py-0">
              <CardContent className="p-3">
                <div className="text-sm font-semibold">需要你确认</div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                  即将执行 <Badge variant="outline">{runtime.approval.tool}</Badge>
                  {runtime.approval.reason ? `：${runtime.approval.reason}` : ''}
                </div>
                <pre className="mt-2 max-h-64 overflow-auto rounded-md border bg-panel p-2 font-mono text-xs whitespace-pre-wrap">
                  {JSON.stringify(runtime.approval.args, null, 2)}
                </pre>
                <p className="mt-2 text-xs text-muted-foreground">
                  审批人角色才能决议，且不能审批自己发起的操作。
                </p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" disabled={sending} onClick={() => void resolve('approved')}>
                    {sending ? '提交中…' : '批准'}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={sending}
                    onClick={() => void resolve('rejected')}
                  >
                    拒绝
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {runtime.messages.map((msg) => (
            <div
              key={msg.id}
              className={
                msg.role === 'user'
                  ? 'ml-auto max-w-[78%] rounded-xl bg-brand/10 px-3 py-2.5 text-sm leading-relaxed whitespace-pre-wrap'
                  : 'text-sm leading-relaxed whitespace-pre-wrap'
              }
            >
              {msg.text}
              {msg.streaming && <span className="text-muted-foreground">▍</span>}
              {msg.citations?.length ? (
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {msg.citations.map((c: Citation, i: number) => (
                    <Tooltip key={c.chunk_id}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          className="text-xs text-brand underline-offset-4 hover:underline"
                          onClick={() => setActiveCitation(c)}
                        >
                          [{i + 1}] {c.title}
                          {c.page ? ` p.${c.page}` : ''}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-80">{c.snippet}</TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              ) : null}
              {msg.role === 'assistant' &&
              ((msg.timeline?.length ?? 0) > 0 || msg.timelineAvailable === false) ? (
                <Timeline
                  items={msg.timeline ?? []}
                  available={msg.timelineAvailable ?? true}
                  truncated={Boolean(msg.timelineTruncated)}
                />
              ) : null}
            </div>
          ))}

          {runtime.error && (
            <Card className="border-danger/30 bg-danger/5">
              <CardContent className="flex flex-wrap items-center gap-3 p-3">
                <span className="min-w-0 flex-1 text-sm text-danger">{runtime.error}</span>
                {runtime.phase === 'failed' && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={sending}
                    onClick={() => void retry()}
                  >
                    重试
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <CitationPreviewDialog citation={activeCitation} onClose={() => setActiveCitation(null)} />

        <div className="border-t px-3 py-3 sm:px-4">
          <div className="flex flex-wrap items-end gap-2">
            <Textarea
              value={text}
              rows={1}
              aria-label="消息输入框"
              placeholder="描述你的问题…（Enter 发送，Shift+Enter 换行）"
              className="max-h-40 min-h-9 min-w-0 flex-1 resize-none py-2 text-sm"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void onSend();
                }
              }}
            />
            {sending ? (
              <Button variant="destructive" onClick={abort}>
                停止
              </Button>
            ) : (
              <Button onClick={() => void onSend()}>发送</Button>
            )}
            <Button variant="outline" onClick={onNewSession} disabled={sending}>
              新会话
            </Button>
          </div>
          <div className="mt-2 text-xs text-muted-foreground">
            状态：{PHASE_LABEL[runtime.phase] ?? runtime.phase}
            {runtime.costCents !== null
              ? ` · 本轮成本 ¥${(runtime.costCents / 100).toFixed(2)}`
              : ''}
            {historyLoading ? ' · 历史会话加载中…' : ''}
          </div>
        </div>
      </div>
    </div>
  );
}
