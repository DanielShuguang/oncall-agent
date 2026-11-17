/** 运行详情 / 回放（W4 D20）：用事件归约器重建整场 run，不重新执行 Agent。 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getRun, getAllRunEvents, type RunDetail } from '@/api/runs';
import { initialRuntime, runtimeReducer, type Runtime } from '@/features/chat/machine';
import type { RunEvent } from '@/features/chat/types';
import { failureLabel, formatTime, STATUS_TONES, statusLabel } from '@/lib/format';
import {
  Conversation,
  ModelCalls,
  RawEvents,
  RunMetrics,
  StepTimeline,
  ToolCalls,
} from './RunDetailSections';

function replay(events: RunEvent[]): Runtime {
  return events.reduce<Runtime>((state, event) => runtimeReducer(state, event), {
    ...initialRuntime,
    phase: 'running',
  });
}

function subtitle(run: RunDetail): string {
  if (run.content_pruned_at) {
    return `正文已过保留期清理（${formatTime(run.content_pruned_at)}）`;
  }
  if (run.content_redacted) return '回答引用的文档已不可见，内容不再展示';
  if (run.events_pruned_at) return `事件已过保留期清理（${formatTime(run.events_pruned_at)}）`;
  return `${run.event_count} 条事件 · 重放自事件表`;
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
            {formatTime(run.started_at)} · {subtitle(run)}
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/runs">返回列表</Link>
        </Button>
      </div>

      <RunMetrics run={run} />

      {run.status === 'failed' && (
        <Card className="mb-4 border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">
            {run.error_code ?? 'UNKNOWN'} · {failureLabel(run.failure_category)}
          </CardContent>
        </Card>
      )}

      {run.content_pruned_at ? (
        <Card className="mb-4 border-line bg-panel">
          <CardContent className="p-3 text-xs text-muted-foreground">
            {`正文已过保留期，于 ${formatTime(run.content_pruned_at)} 被清空：问题与回答不再保留，回放也不可用；运行摘要、模型计量与失败归因仍然可查。这是保留策略，不是运行失败。`}
          </CardContent>
        </Card>
      ) : (
        run.events_pruned_at && (
          <Card className="mb-4 border-line bg-panel">
            <CardContent className="p-3 text-xs text-muted-foreground">
              {`事件已过保留期，于 ${formatTime(run.events_pruned_at)} 被清理：步骤时间线、工具调用与对话回放不再可用；运行摘要、模型计量与失败归因仍保留。`}
            </CardContent>
          </Card>
        )
      )}

      {!run.content_pruned_at && run.content_redacted && (
        <Card className="mb-4 border-line bg-panel">
          <CardContent className="p-3 text-xs text-muted-foreground">
            该回答引用的知识库文档已不可见（可见范围变更或已删除）：回答正文、对话回放与
            事件不再展示；运行摘要、模型计量与失败归因仍保留。可见范围恢复后内容自动恢复。
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <StepTimeline runtime={runtime} run={run} />
        <ToolCalls runtime={runtime} run={run} />
      </div>

      <Conversation runtime={runtime} run={run} />
      <ModelCalls run={run} />
      <RawEvents events={events} />
    </div>
  );
}
