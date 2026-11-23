/** 回滚前的差异预览与二次确认（ADR-0113、ADR-0117）。 */

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { previewToolRollback, type ToolChange, type ToolRollbackPreview } from '@/api/tools';
import { describeSnapshot, formatTime } from './toolHistoryFormat';

interface RollbackPreviewDialogProps {
  change: ToolChange | null;
  onClose: () => void;
  onConfirm: () => void;
}

interface PreviewState {
  changeId: number;
  data: ToolRollbackPreview;
}

interface PreviewError {
  changeId: number;
  message: string;
}

export function RollbackPreviewDialog({ change, onClose, onConfirm }: RollbackPreviewDialogProps) {
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewError, setPreviewError] = useState<PreviewError | null>(null);
  const showPreview = change !== null && preview?.changeId === change.id ? preview.data : null;
  const showError =
    change !== null && previewError?.changeId === change.id ? previewError.message : null;
  const loading = change !== null && showPreview === null && showError === null;

  useEffect(() => {
    if (!change) return;
    let cancelled = false;
    void previewToolRollback(change.tool_name, change.id)
      .then((data) => {
        if (!cancelled) setPreview({ changeId: change.id, data });
        return data;
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewError({
            changeId: change.id,
            message: '无法读取执行瞬间的当前配置，请关闭后重试',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [change]);

  const target = showPreview ? showPreview.target : (change?.before ?? null);
  const canConfirm =
    showPreview !== null &&
    showPreview.changed &&
    showPreview.rollbackable &&
    !loading &&
    showError === null;

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
            <span className="text-muted-foreground">记录时配置（变更后）：</span>{' '}
            <span className="font-mono">{describeSnapshot(change?.after ?? null)}</span>
          </div>
          <div className="rounded-md border border-line bg-canvas p-2">
            <span className="text-muted-foreground">执行瞬间当前配置：</span>{' '}
            <span className="font-mono">
              {loading
                ? '读取中…'
                : showPreview
                  ? describeSnapshot(showPreview.current)
                  : '读取失败'}
            </span>
          </div>
          <div className="rounded-md border border-brand/30 bg-brand/5 p-2">
            <span className="text-muted-foreground">回滚目标：</span>{' '}
            <span className="font-mono">{describeSnapshot(target)}</span>
          </div>
          {showPreview && !showPreview.changed ? (
            <p className="text-xs text-muted-foreground">
              当前已是目标状态，回滚不会新增变更记录。
            </p>
          ) : null}
          {showPreview && !showPreview.rollbackable ? (
            <p className="text-xs text-warn">{showPreview.reason ?? '当前工具不可回滚。'}</p>
          ) : null}
          {showError ? <p className="text-xs text-warn">{showError}</p> : null}
          <p className="text-xs text-muted-foreground">
            回滚会新增一条变更记录，不删除原记录。执行时服务端会再次读取当前配置并以那时为准；
            当前实例立即生效，多副本部署下最多 2 秒生效。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button disabled={!canConfirm} onClick={onConfirm}>
            确认回滚
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
