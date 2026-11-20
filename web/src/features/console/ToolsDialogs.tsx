/** 试调用与变更历史弹窗，从 ToolsPage 拆出。 */

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { ToolChange, ToolInfo, ToolOverrideSnapshot, ToolTestResponse } from '@/api/tools';

export interface TestState {
  tool: ToolInfo;
  argsText: string;
  running: boolean;
  result: ToolTestResponse | null;
  error: string | null;
}

export interface HistoryState {
  tool: ToolInfo;
  loading: boolean;
  items: ToolChange[];
  error: string | null;
  changedFrom: string;
  changedTo: string;
  filterError: string | null;
  /** 最近一次实际查询使用的窗口；导出必须与列表一致，不能使用未应用的草稿。 */
  appliedFrom: string;
  appliedTo: string;
  /** 首屏总数；后续页为 null。 */
  total: number | null;
  nextCursor: string | null;
  loadingMore: boolean;
  /** 加载更多失败时保留已加载列表，只在底部提示。 */
  loadMoreError: string | null;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function describeSnapshot(snapshot: ToolOverrideSnapshot | null): string {
  if (snapshot === null) return '代码默认';
  const enabled = snapshot.enabled === null ? '启用继承' : snapshot.enabled ? '启用' : '禁用';
  const roles =
    snapshot.roles === null
      ? '角色继承'
      : snapshot.roles.length === 0
        ? '所有登录用户'
        : snapshot.roles.join('、');
  return `${enabled} · ${roles}`;
}

function sourceLabel(source: string): string {
  if (source === 'matrix') return '权限矩阵';
  if (source === 'tool') return '工具开关';
  return source;
}

interface ToolsDialogsProps {
  tester: TestState | null;
  history: HistoryState | null;
  onTesterChange: (state: TestState | null) => void;
  onHistoryChange: (state: HistoryState | null) => void;
  onReloadHistory: () => void;
  onClearHistoryFilters: () => void;
  onLoadMoreHistory: () => void;
  onExportHistory: () => void;
  exportingHistory: boolean;
  historyExportMessage: string | null;
  onRunTest: () => void;
}

export function ToolsDialogs({
  tester,
  history,
  onTesterChange,
  onHistoryChange,
  onReloadHistory,
  onClearHistoryFilters,
  onLoadMoreHistory,
  onExportHistory,
  exportingHistory,
  historyExportMessage,
  onRunTest,
}: ToolsDialogsProps) {
  return (
    <>
      <Dialog
        open={tester !== null}
        onOpenChange={(open) => {
          if (!open) onTesterChange(null);
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">{tester?.tool.name}</DialogTitle>
            <DialogDescription>
              {tester?.tool.description}
              {tester?.tool.is_write
                ? ' · 写操作：试调用只验证审批闸门，不会真正执行'
                : ' · 只读：会真实执行 handler'}
            </DialogDescription>
          </DialogHeader>

          <div>
            <div className="mb-1 text-xs text-muted-foreground">参数（JSON）</div>
            <Textarea
              rows={8}
              aria-label="试调用参数"
              className="font-mono text-xs"
              value={tester?.argsText ?? ''}
              disabled={tester?.running}
              onChange={(event) => {
                if (tester) onTesterChange({ ...tester, argsText: event.target.value });
              }}
            />
            <details className="mt-2 text-[11px] text-muted-foreground">
              <summary className="cursor-pointer select-none">查看只读 schema</summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-canvas/50 p-2 font-mono text-[11px] whitespace-pre-wrap">
                {JSON.stringify(tester?.tool.input_schema ?? {}, null, 2)}
              </pre>
            </details>
          </div>

          {tester?.error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {tester.error}
            </div>
          )}

          {tester?.result && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant={tester.result.status === 'ok' ? 'secondary' : 'destructive'}>
                  {tester.result.status}
                </Badge>
                <span className="text-muted-foreground">
                  decision={tester.result.decision} · {tester.result.duration_ms}ms · 尝试{' '}
                  {tester.result.attempts} 次
                </span>
              </div>
              {tester.result.error && (
                <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
                  {tester.result.error}
                  {tester.result.error_kind ? `（${tester.result.error_kind}）` : ''}
                </div>
              )}
              <pre className="max-h-64 overflow-auto rounded-md border bg-panel p-3 font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(tester.result.result, null, 2)}
              </pre>
              {tester.result.decision === 'requires_approval' && (
                <p className="text-[11px] text-muted-foreground">
                  真实对话里会生成审批卡；审批人通过后才执行 handler。
                </p>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => onTesterChange(null)}>
              关闭
            </Button>
            <Button disabled={tester?.running} onClick={onRunTest}>
              {tester?.running ? '执行中…' : '执行'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={history !== null}
        onOpenChange={(open) => {
          if (!open) onHistoryChange(null);
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">变更历史 · {history?.tool.name}</DialogTitle>
            <DialogDescription>
              只记录管理页真正改变配置的写入；试调用与运行中的工具调用不会产生记录。
            </DialogDescription>
          </DialogHeader>

          {history && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-end gap-2">
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">开始日期（UTC）</div>
                  <Input
                    aria-label="变更开始日期"
                    className="w-36"
                    type="date"
                    value={history.changedFrom}
                    onChange={(event) =>
                      onHistoryChange({ ...history, changedFrom: event.target.value })
                    }
                  />
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">结束日期（UTC）</div>
                  <Input
                    aria-label="变更结束日期"
                    className="w-36"
                    type="date"
                    value={history.changedTo}
                    onChange={(event) =>
                      onHistoryChange({ ...history, changedTo: event.target.value })
                    }
                  />
                </div>
                <Button size="sm" variant="outline" onClick={onReloadHistory}>
                  应用
                </Button>
                <Button size="sm" variant="ghost" onClick={onClearHistoryFilters}>
                  清除
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={exportingHistory || history.loading}
                  onClick={onExportHistory}
                >
                  {exportingHistory ? '导出中…' : '导出 CSV'}
                </Button>
              </div>
              {history.filterError && (
                <div className="text-xs text-danger">{history.filterError}</div>
              )}
              {historyExportMessage && (
                <div className="text-xs text-muted-foreground">{historyExportMessage}</div>
              )}
            </div>
          )}

          {history?.loading ? (
            <div className="p-6 text-center text-xs text-muted-foreground">加载中…</div>
          ) : history?.error ? (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {history.error}
            </div>
          ) : history && history.items.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              {history.appliedFrom ? '该日期范围内没有配置变更记录。' : '还没有配置变更记录。'}
            </div>
          ) : (
            <div className="max-h-96 space-y-2 overflow-auto">
              {history?.items.map((item) => (
                <div key={item.id} className="rounded-md border p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{sourceLabel(item.source)}</Badge>
                    <span className="text-muted-foreground">{formatTime(item.changed_at)}</span>
                    <span className="font-mono">{item.changed_by}</span>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {describeSnapshot(item.before)} → {describeSnapshot(item.after)}
                  </div>
                </div>
              ))}
              {history?.loadMoreError && (
                <div className="text-xs text-danger">{history.loadMoreError}</div>
              )}
              <div className="flex items-center justify-between gap-2 pt-1 text-xs text-muted-foreground">
                <span>
                  {history?.total === null || history?.total === undefined
                    ? `已加载 ${history?.items.length ?? 0} 条`
                    : `共 ${history.total} 条 · 已加载 ${history.items.length} 条`}
                </span>
                {history?.nextCursor && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={history.loadingMore}
                    onClick={onLoadMoreHistory}
                  >
                    {history.loadingMore ? '加载中…' : '加载更多'}
                  </Button>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => onHistoryChange(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
