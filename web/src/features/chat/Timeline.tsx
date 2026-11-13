/** 历史回答的运行过程回放（ADR-0035）。
 *
 * 只读展示工具调用与审批，不回放 message.delta、步骤事件和审批人身份。
 * 事件过了保留期时由 `available=false` 明确说明「不可用」，不能装作没有调用。
 */

import { Badge } from '@/components/ui/badge';
import type { ApprovalTimelineItem, TimelineItem, ToolTimelineItem } from './types';

const STATUS_LABEL: Record<string, string> = {
  running: '执行中',
  ok: '成功',
  error: '失败',
  timeout: '超时',
  denied: '已拒绝',
  requires_approval: '等待审批',
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
};

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

interface TruncatedPreview {
  truncated: true;
  original_chars: number;
  preview: string;
}

function asTruncatedPreview(value: unknown): TruncatedPreview | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as Record<string, unknown>;
  if (record.truncated !== true || typeof record.preview !== 'string') return null;
  return {
    truncated: true,
    original_chars: typeof record.original_chars === 'number' ? record.original_chars : 0,
    preview: record.preview,
  };
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const cut = asTruncatedPreview(value);
  return (
    <>
      <div className="mt-2 text-[11px] text-muted-foreground">
        {cut ? `${label}（原始 ${cut.original_chars} 字符，已截断）` : label}
      </div>
      <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-panel p-2 font-mono text-[11px] whitespace-pre-wrap">
        {cut ? cut.preview : JSON.stringify(value, null, 2)}
      </pre>
    </>
  );
}

function ToolRow({ item }: { item: ToolTimelineItem }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={item.write ? 'destructive' : 'secondary'}>{item.tool}</Badge>
        <span className="text-muted-foreground">{statusLabel(item.status)}</span>
        {typeof item.duration_ms === 'number' && (
          <span className="text-muted-foreground">· {item.duration_ms}ms</span>
        )}
        {typeof item.attempts === 'number' && item.attempts > 1 && (
          <span className="text-muted-foreground">· 重试{item.attempts - 1}次</span>
        )}
      </div>
      <JsonBlock label="参数" value={item.args} />
      {item.result !== undefined && <JsonBlock label="结果" value={item.result} />}
      {item.error && <div className="mt-1 text-destructive">{item.error}</div>}
    </div>
  );
}

function ApprovalRow({ item }: { item: ApprovalTimelineItem }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{item.tool}</Badge>
        <span className="text-muted-foreground">{statusLabel(item.status)}</span>
        <span className="text-muted-foreground">· 风险 {item.risk_level}</span>
      </div>
      {item.reason && <div className="mt-1 text-muted-foreground">审批理由：{item.reason}</div>}
      {item.decision_reason && (
        <div className="mt-1 text-muted-foreground">决议说明：{item.decision_reason}</div>
      )}
      <JsonBlock label="参数" value={item.args} />
    </div>
  );
}

interface Props {
  items: TimelineItem[];
  available: boolean;
  truncated: boolean;
}

export function Timeline({ items, available, truncated }: Props) {
  if (!available) {
    return <p className="mt-2 text-xs text-muted-foreground">运行过程记录已过保留期，无法回看。</p>;
  }
  if (items.length === 0) return null;

  const toolCount = items.filter((item) => item.kind === 'tool').length;
  const approvalCount = items.length - toolCount;

  return (
    <details className="mt-2 rounded-lg border bg-panel/40 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground">
        运行过程（{toolCount} 个工具调用
        {approvalCount > 0 ? `，${approvalCount} 次审批` : ''}）
      </summary>
      <div className="mt-2 space-y-2">
        {items.map((item) => {
          const key = `${item.kind}_${item.seq}`;
          return item.kind === 'tool' ? (
            <ToolRow key={key} item={item} />
          ) : (
            <ApprovalRow key={key} item={item} />
          );
        })}
      </div>
      {truncated && (
        <p className="mt-2 text-muted-foreground">
          事件较长，只显示最早的 20 项，后续工具调用未展开。
        </p>
      )}
    </details>
  );
}
