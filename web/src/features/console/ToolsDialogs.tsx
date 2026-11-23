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
import { Textarea } from '@/components/ui/textarea';
import { ToolHistoryFilterBar } from './ToolHistoryFilterBar';
import type { ToolChange, ToolInfo, ToolTestResponse } from '@/api/tools';
import { describeSnapshot, formatTime, sourceLabel, type HistoryState } from './toolHistoryFormat';

export interface TestState {
  tool: ToolInfo;
  argsText: string;
  running: boolean;
  result: ToolTestResponse | null;
  error: string | null;
}

export type { HistoryState } from './toolHistoryFormat';

interface ToolsDialogsProps {
  tester: TestState | null;
  history: HistoryState | null;
  onTesterChange: (state: TestState | null) => void;
  onHistoryChange: (state: HistoryState | null) => void;
  onReloadHistory: () => void;
  onClearHistoryFilters: () => void;
  onLoadMoreHistory: () => void;
  onReloadExpiredHistory: () => void;
  onExportHistory: () => void;
  onPreviewRollback: (change: ToolChange, batchIds?: number[]) => void;
  onToggleHistorySelection: (changeId: number) => void;
  onBatchRollback: () => void;
  batchRolling: boolean;
  rollingBackId: number | null;
  rollbackMessage: string | null;
  rollbackError: string | null;
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
  onReloadExpiredHistory,
  onExportHistory,
  onPreviewRollback,
  onToggleHistorySelection,
  onBatchRollback,
  batchRolling,
  rollingBackId,
  rollbackMessage,
  rollbackError,
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
            <ToolHistoryFilterBar
              history={history}
              onChange={onHistoryChange}
              onReload={onReloadHistory}
              onClear={onClearHistoryFilters}
              onExport={onExportHistory}
              exporting={exportingHistory}
              exportMessage={historyExportMessage}
            />
          )}

          {history?.loading ? (
            <div className="p-6 text-center text-xs text-muted-foreground">加载中…</div>
          ) : history?.error ? (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {history.error}
            </div>
          ) : history && history.items.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              {history.appliedFrom || history.appliedBy || history.appliedSource
                ? '当前过滤条件下没有配置变更记录。'
                : '还没有配置变更记录。'}
            </div>
          ) : (
            <div className="space-y-2">
              {(history?.selectedIds.length ?? 0) > 0 && (
                <div className="flex items-center justify-between gap-2 rounded-md border border-brand/30 bg-brand/5 p-2 text-xs">
                  <span>已选 {history?.selectedIds.length} 条，回滚到最早一条之前</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={batchRolling || rollingBackId !== null}
                    onClick={onBatchRollback}
                  >
                    {batchRolling ? '回滚中…' : '批量回滚'}
                  </Button>
                </div>
              )}
              <div className="max-h-96 space-y-2 overflow-auto">
                {history?.items.map((item) => (
                  <div key={item.id} className="rounded-md border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="checkbox"
                        aria-label={`选择变更 ${item.id}`}
                        checked={history.selectedIds.includes(item.id)}
                        disabled={batchRolling || rollingBackId !== null}
                        onChange={() => onToggleHistorySelection(item.id)}
                      />
                      <Badge variant="outline">{sourceLabel(item.source)}</Badge>
                      <span className="text-muted-foreground">{formatTime(item.changed_at)}</span>
                      <span className="font-mono">{item.changed_by}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                      <span className="text-muted-foreground">
                        {describeSnapshot(item.before)} → {describeSnapshot(item.after)}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={batchRolling || rollingBackId !== null}
                        onClick={() => onPreviewRollback(item)}
                      >
                        {rollingBackId === item.id ? '回滚中…' : '回滚'}
                      </Button>
                    </div>
                  </div>
                ))}
                {rollbackMessage && (
                  <div className="rounded-md border border-ok/30 bg-ok/5 p-2 text-xs text-ok">
                    {rollbackMessage}
                  </div>
                )}
                {rollbackError && (
                  <div className="rounded-md border border-danger/30 bg-danger/5 p-2 text-xs text-danger">
                    {rollbackError}
                  </div>
                )}
                {history?.loadMoreError && (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-danger">
                    <span>{history.loadMoreError}</span>
                    {history.loadMoreErrorCode === 'CURSOR_EXPIRED' && (
                      <Button size="sm" variant="outline" onClick={onReloadExpiredHistory}>
                        重新加载
                      </Button>
                    )}
                  </div>
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
