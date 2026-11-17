/** 批量移除的底部操作条（ADR-0072）。 */

import { Button } from '@/components/ui/button';

interface SessionBatchBarProps {
  mode: boolean;
  hiding: boolean;
  selectedCount: number;
  sessionsCount: number;
  confirming: boolean;
  allSelected: boolean;
  onToggleAll: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onHideSelected: () => void;
}

export function SessionBatchBar({
  mode,
  hiding,
  selectedCount,
  sessionsCount,
  confirming,
  allSelected,
  onToggleAll,
  onConfirm,
  onCancel,
  onHideSelected,
}: SessionBatchBarProps) {
  if (!mode) return null;

  return (
    <div className="space-y-2 border-t pt-2.5">
      {confirming ? (
        <div className="space-y-2 rounded-xl border border-danger/30 bg-danger/5 p-2.5">
          <p className="text-xs text-muted-foreground">
            从列表移除选中的 {selectedCount} 个会话？run 与审批仍按保留期保存。
          </p>
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="outline" type="button" onClick={onCancel}>
              取消
            </Button>
            <Button
              size="sm"
              variant="destructive"
              type="button"
              disabled={hiding || selectedCount === 0}
              onClick={onHideSelected}
            >
              {hiding ? '移除中…' : '确认移除'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-1">
          <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onToggleAll}
              disabled={sessionsCount === 0 || hiding}
              aria-label="全选已加载会话"
            />
            全选已加载
          </label>
          <Button
            size="sm"
            variant="outline"
            disabled={selectedCount === 0 || hiding}
            onClick={onConfirm}
          >
            {hiding ? '移除中…' : `移除选中（${selectedCount}）`}
          </Button>
        </div>
      )}
    </div>
  );
}
