import { useState } from 'react';
import { cn } from 'cn';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
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
  const { runtime, sending, send, abort, reset } = useChat();
  const [text, setText] = useState('');

  const onSend = async () => {
    const value = text.trim();
    if (!value) return;
    setText('');
    await send(value);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div aria-live="polite" className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        {runtime.messages.length === 0 && (
          <Card className="gap-0 py-0">
            <CardContent className="p-3 text-sm">
              试试：「我电脑连不上打印机了」　或　「我要申请开单报修打印机」
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
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled>
                  批准（W3 D14 接通）
                </Button>
                <Button size="sm" variant="outline" disabled>
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
          </div>
        ))}

        {runtime.error && (
          <Alert variant="destructive">
            <AlertTitle>{runtime.error}</AlertTitle>
          </Alert>
        )}
      </div>

      <div className="border-t px-4 py-3">
        <div className="flex items-end gap-2">
          <Textarea
            value={text}
            rows={1}
            aria-label="消息输入框"
            placeholder="描述你的问题…（Enter 发送，Shift+Enter 换行）"
            className="max-h-40 min-h-9 resize-none py-2 text-sm"
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
          <Button variant="outline" onClick={reset} disabled={sending}>
            新会话
          </Button>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          状态：{PHASE_LABEL[runtime.phase] ?? runtime.phase}
          {runtime.costCents !== null ? ` · 本轮成本 ¥${(runtime.costCents / 100).toFixed(2)}` : ''}
        </div>
      </div>
    </div>
  );
}
