import { cn } from 'cn';
import { Bot, Info, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Runtime } from './machine';
import { REDACTED_NOTE } from './history';
import { Timeline } from './Timeline';
import type { Citation } from './types';

interface Props {
  runtime: Runtime;
  sending: boolean;
  resolve: (decision: 'approved' | 'rejected') => Promise<void>;
  onRetry: () => Promise<void>;
  historyCursor: string | null;
  historyOlderLoading: boolean;
  onLoadEarlier: () => void;
  onSuggestion: (text: string) => void;
  onCitation: (citation: Citation) => void;
}

export function ChatMessages({
  runtime,
  sending,
  resolve,
  onRetry,
  historyCursor,
  historyOlderLoading,
  onLoadEarlier,
  onSuggestion,
  onCitation,
}: Props) {
  return (
    <div
      aria-live="polite"
      className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-6"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5">
        {historyCursor && (
          <div className="flex justify-center">
            <Button
              size="sm"
              variant="outline"
              disabled={historyOlderLoading}
              onClick={onLoadEarlier}
            >
              {historyOlderLoading ? '加载中…' : '加载更早的对话'}
            </Button>
          </div>
        )}
        {runtime.messages.length === 0 && (
          <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
            <span className="grid size-14 place-items-center rounded-2xl bg-brand/10 text-brand">
              <Sparkles className="size-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold tracking-tight">今天想解决什么问题？</h2>
            <p className="mt-1.5 max-w-md text-sm leading-6 text-muted-foreground">
              查资产、查工单、报修或申请软件，都可以直接用一句话说明。
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {['VPN 连不上怎么办', '我电脑连不上打印机了', '帮我申请安装设计软件'].map(
                (suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="rounded-full border bg-panel px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-brand/30 hover:text-brand"
                    onClick={() => onSuggestion(suggestion)}
                  >
                    {suggestion}
                  </button>
                ),
              )}
            </div>
          </div>
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

        {runtime.messages.map((msg) => {
          const assistant = msg.role === 'assistant';
          const redacted = assistant && msg.text === REDACTED_NOTE;
          return (
            <div key={msg.id} className={cn('flex gap-3', !assistant && 'justify-end')}>
              {assistant && (
                <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-brand/10 text-brand">
                  <Bot className="size-4" />
                </span>
              )}
              <div className={cn('flex min-w-0 max-w-[85%] flex-col', !assistant && 'items-end')}>
                <div
                  className={cn(
                    'text-sm leading-7 whitespace-pre-wrap',
                    redacted
                      ? 'rounded-2xl rounded-tl-sm border border-dashed bg-muted/30 px-4 py-3 text-muted-foreground'
                      : assistant
                        ? 'rounded-2xl rounded-tl-sm border bg-canvas/60 px-4 py-3 text-ink'
                        : 'rounded-2xl rounded-tr-sm bg-brand px-4 py-2.5 text-primary-foreground shadow-sm',
                  )}
                >
                  {redacted ? (
                    <span className="flex items-center gap-2 text-xs leading-5">
                      <Info className="size-3.5 shrink-0" />
                      回答引用的文档已不可见，正文不再展示
                    </span>
                  ) : (
                    msg.text
                  )}
                  {msg.streaming && <span className="text-muted-foreground">▍</span>}
                </div>
                {msg.citations?.length ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {msg.citations.map((citation: Citation, index: number) => (
                      <Tooltip key={citation.chunk_id}>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="rounded-full border bg-panel px-2.5 py-1 text-xs text-brand transition-colors hover:border-brand/30 hover:bg-brand/5"
                            onClick={() => onCitation(citation)}
                          >
                            [{index + 1}] {citation.title}
                            {citation.page ? ` p.${citation.page}` : ''}
                          </button>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">{citation.snippet}</TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                ) : null}
                {assistant &&
                ((msg.timeline?.length ?? 0) > 0 || msg.timelineAvailable === false) ? (
                  <Timeline
                    items={msg.timeline ?? []}
                    available={msg.timelineAvailable ?? true}
                    truncated={Boolean(msg.timelineTruncated)}
                  />
                ) : null}
              </div>
            </div>
          );
        })}

        {runtime.error && (
          <Card className="border-danger/30 bg-danger/5">
            <CardContent className="flex flex-wrap items-center gap-3 p-3">
              <span className="min-w-0 flex-1 text-sm text-danger">{runtime.error}</span>
              {runtime.phase === 'failed' && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={sending}
                  onClick={() => void onRetry()}
                >
                  重试
                </Button>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
