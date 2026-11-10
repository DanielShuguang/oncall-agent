/** 运行详情 / 回放（W4 D20）：用事件归约器重建整场 run，不重新执行 Agent。 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getRun, getAllRunEvents, type RunDetail } from '@/api/runs';
import { initialRuntime, runtimeReducer, type Runtime } from '@/features/chat/machine';
import type { RunEvent } from '@/features/chat/types';
import {
  failureLabel,
  formatCents,
  formatDuration,
  formatTime,
  STATUS_TONES,
  statusLabel,
} from '@/lib/format';

function replay(events: RunEvent[]): Runtime {
  return events.reduce<Runtime>((state, event) => runtimeReducer(state, event), {
    ...initialRuntime,
    phase: 'running',
  });
}

export default function RunDetailPage() {
  const { id = '' } = useParams();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [detail, list] = await Promise.all([getRun(id), getAllRunEvents(id)]);
        if (cancelled) return;
        setRun(detail);
        setEvents(list);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const runtime = useMemo(() => replay(events), [events]);

  if (loading) {
    return <div className="flex-1 p-6 text-sm text-muted-foreground">加载事件中…</div>;
  }
  if (error || !run) {
    return (
      <div className="flex-1 space-y-3 p-6">
        <div className="text-sm text-danger">{error ?? 'run 不存在'}</div>
        <Button asChild variant="outline" size="sm">
          <Link to="/runs">返回运行列表</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="m-0 font-mono text-sm font-semibold">{run.run_id}</h2>
            <Badge variant="outline" className={STATUS_TONES[run.status]}>
              {statusLabel(run.status)}
            </Badge>
          </div>
          <p className="mt-1 mb-0 text-xs text-muted-foreground">
            {formatTime(run.started_at)} ·{' '}
            {run.events_pruned_at
              ? `事件已过保留期清理（${formatTime(run.events_pruned_at)}）`
              : `${run.event_count} 条事件 · 重放自事件表`}
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/runs">返回列表</Link>
        </Button>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="模型" value={run.model ?? '-'} />
        <Metric label="步数" value={`${run.step_count}/${run.max_steps}`} />
        <Metric label="Token" value={`${run.token_in} in / ${run.token_out} out`} />
        <Metric label="成本" value={formatCents(run.cost_cents)} />
        <Metric label="模型调用" value={`${run.model_calls.length} 次`} />
        <Metric label="耗时" value={formatDuration(run.started_at, run.finished_at)} />
        <Metric label="意图" value={run.intent ?? '-'} />
        <Metric
          label={run.status === 'failed' ? '失败归因' : '结束时间'}
          value={
            run.status === 'failed'
              ? `${failureLabel(run.failure_category)} / ${run.error_code ?? '-'}`
              : formatTime(run.finished_at)
          }
        />
      </div>

      {run.status === 'failed' && (
        <Card className="mb-4 border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">
            {run.error_code ?? 'UNKNOWN'} · {failureLabel(run.failure_category)}
          </CardContent>
        </Card>
      )}

      {run.events_pruned_at && (
        <Card className="mb-4 border-line bg-panel">
          <CardContent className="p-3 text-xs text-muted-foreground">
            {`事件已过保留期，于 ${formatTime(run.events_pruned_at)} 被清理：步骤时间线、工具调用与对话回放不再可用；运行摘要、模型计量与失败归因仍保留。`}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">步骤时间线</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {runtime.steps.length === 0 && (
              <div className="text-xs text-muted-foreground">
                {run.events_pruned_at ? '事件已清理，无法重建时间线' : '没有步骤事件'}
              </div>
            )}
            {runtime.steps.map((step) => (
              <div key={`${step.node}-${step.seq}`} className="flex items-start gap-2 text-xs">
                <span
                  className={`mt-1 size-1.5 shrink-0 rounded-full ${
                    step.status === 'done' ? 'bg-ok' : 'bg-brand'
                  }`}
                />
                <div className="min-w-0">
                  <span className="font-medium">{step.title || step.node}</span>
                  {step.durationMs !== undefined && (
                    <span className="ml-2 text-muted-foreground">{step.durationMs}ms</span>
                  )}
                  <div className="text-muted-foreground">{step.summary ?? '进行中'}</div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">工具调用</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {runtime.tools.length === 0 && (
              <div className="text-xs text-muted-foreground">
                {run.events_pruned_at ? '事件已清理，工具调用记录不可用' : '没有工具调用'}
              </div>
            )}
            {runtime.tools.map((tool) => (
              <div key={tool.callId} className="rounded-md border p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{tool.tool}</span>
                  <Badge variant="secondary">{tool.status}</Badge>
                </div>
                <pre className="mt-1 mb-0 overflow-x-auto text-[11px] text-muted-foreground">
                  {JSON.stringify(tool.args, null, 2)}
                </pre>
                {tool.error && <div className="mt-1 text-danger">{tool.error}</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">对话回放</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs">
            <div className="text-muted-foreground">用户</div>
            <div className="mt-0.5">{run.input}</div>
          </div>
          {runtime.messages
            .filter((message) => message.role === 'assistant' && message.text)
            .map((message) => (
              <div key={message.id} className="text-xs">
                <div className="text-muted-foreground">助手</div>
                <div className="mt-0.5 whitespace-pre-wrap">{message.text}</div>
                {message.citations && message.citations.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {message.citations.map((citation, index) => (
                      <Badge
                        key={`${citation.chunk_id}-${citation.ord}`}
                        variant="outline"
                        className="text-[11px]"
                      >
                        [{index + 1}] {citation.title}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          {run.events_pruned_at && run.output && (
            <div className="text-xs">
              <div className="text-muted-foreground">助手（最终回答，来自 run 摘要）</div>
              <div className="mt-0.5 whitespace-pre-wrap">{run.output}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">引用角标随事件清理不可用</div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">模型计量</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>节点</TableHead>
                <TableHead>模型</TableHead>
                <TableHead className="text-right">token in</TableHead>
                <TableHead className="text-right">token out</TableHead>
                <TableHead className="text-right">成本</TableHead>
                <TableHead className="text-right">延迟</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {run.model_calls.map((call) => (
                <TableRow key={`${call.created_at}-${call.step}-${call.model}-${call.token_in}`}>
                  <TableCell className="text-xs">{call.step}</TableCell>
                  <TableCell className="text-xs">{call.model}</TableCell>
                  <TableCell className="text-right text-xs">{call.token_in}</TableCell>
                  <TableCell className="text-right text-xs">{call.token_out}</TableCell>
                  <TableCell className="text-right text-xs">
                    {formatCents(call.cost_cents)}
                  </TableCell>
                  <TableCell className="text-right text-xs">{call.latency_ms}ms</TableCell>
                  <TableCell className="text-xs">{call.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {run.model_calls.length === 0 && (
            <div className="p-4 text-xs text-muted-foreground">
              本次 run 没有模型调用（mock 模式或纯规则路径），成本为 0。
            </div>
          )}
        </CardContent>
      </Card>

      <details className="mt-4 rounded-md border bg-panel p-3 text-xs">
        <summary className="cursor-pointer text-muted-foreground">
          原始事件（{events.length} 条，按 seq）
        </summary>
        <div className="mt-2 max-h-72 overflow-y-auto font-mono text-[11px]">
          {events.map((event) => (
            <div key={event.seq} className="border-b border-line/60 py-1 last:border-0">
              #{event.seq} {event.type} {JSON.stringify(event.payload)}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-panel p-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-sm font-medium">{value}</div>
    </div>
  );
}
