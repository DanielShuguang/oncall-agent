import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { RunDetail } from '@/api/runs';
import type { Runtime } from '@/features/chat/machine';
import type { RunEvent } from '@/features/chat/types';
import { failureLabel, formatCents, formatDuration, formatTime } from '@/lib/format';

export function RunMetrics({ run }: { run: RunDetail }) {
  return (
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
  );
}

export function StepTimeline({ runtime, run }: { runtime: Runtime; run: RunDetail }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">步骤时间线</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {runtime.steps.length === 0 && (
          <div className="text-xs text-muted-foreground">
            {run.content_pruned_at
              ? '正文已过保留期，回放不可用'
              : run.content_redacted
                ? '内容已按当前可见性回收，无法重建时间线'
                : run.events_pruned_at
                  ? '事件已清理，无法重建时间线'
                  : '没有步骤事件'}
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
  );
}

export function ToolCalls({ runtime, run }: { runtime: Runtime; run: RunDetail }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">工具调用</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {runtime.tools.length === 0 && (
          <div className="text-xs text-muted-foreground">
            {run.content_pruned_at
              ? '正文已过保留期，工具调用记录不可用'
              : run.content_redacted
                ? '内容已按当前可见性回收，工具调用记录不可用'
                : run.events_pruned_at
                  ? '事件已清理，工具调用记录不可用'
                  : '没有工具调用'}
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
  );
}

export function Conversation({ runtime, run }: { runtime: Runtime; run: RunDetail }) {
  return (
    <Card className="mt-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">对话回放</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-xs">
          <div className="text-muted-foreground">用户</div>
          <div className="mt-0.5">
            {run.content_pruned_at ? '（内容已过保留期，不再保留）' : run.input}
          </div>
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
        {run.events_pruned_at && run.output && !run.content_redacted && (
          <div className="text-xs">
            <div className="text-muted-foreground">助手（最终回答，来自 run 摘要）</div>
            <div className="mt-0.5 whitespace-pre-wrap">{run.output}</div>
            <div className="mt-1 text-[11px] text-muted-foreground">引用角标随事件清理不可用</div>
          </div>
        )}
        {!run.content_pruned_at && run.content_redacted && (
          <div className="text-xs text-muted-foreground">
            助手回答引用的文档已不可见，正文不再展示；这不是运行失败。
          </div>
        )}
        {run.content_pruned_at && (
          <div className="text-xs text-muted-foreground">
            问题与回答正文已过保留期清空，不再展示；这不是运行失败。
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ModelCalls({ run }: { run: RunDetail }) {
  return (
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
                <TableCell className="text-right text-xs">{formatCents(call.cost_cents)}</TableCell>
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
  );
}

export function RawEvents({ events }: { events: RunEvent[] }) {
  return (
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
