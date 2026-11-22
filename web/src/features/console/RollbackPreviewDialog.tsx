/** 回滚前的差异预览与二次确认（ADR-0113）。 */

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { ToolChange } from '@/api/tools';
import { describeSnapshot, formatTime } from './toolHistoryFormat';

interface RollbackPreviewDialogProps {
  change: ToolChange | null;
  onClose: () => void;
  onConfirm: () => void;
}

export function RollbackPreviewDialog({ change, onClose, onConfirm }: RollbackPreviewDialogProps) {
  return (
    <Dialog open={change !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>确认回滚</DialogTitle>
          <DialogDescription>
            将 {change?.tool_name} 回滚到 {change ? formatTime(change.changed_at) : ''}{' '}
            这条变更发生前的配置。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 text-sm">
          <div className="rounded-md border border-line bg-canvas p-2">
            <span className="text-muted-foreground">当前（记录时）：</span>{' '}
            <span className="font-mono">{describeSnapshot(change?.after ?? null)}</span>
          </div>
          <div className="rounded-md border border-brand/30 bg-brand/5 p-2">
            <span className="text-muted-foreground">回滚目标：</span>{' '}
            <span className="font-mono">{describeSnapshot(change?.before ?? null)}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            回滚会新增一条变更记录，不删除原记录。实际写入的 before 是执行瞬间读到的当前配置，
            可能与此处展示的记录快照不同；当前实例立即生效，多副本部署下最多 2 秒生效。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onConfirm}>确认回滚</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
