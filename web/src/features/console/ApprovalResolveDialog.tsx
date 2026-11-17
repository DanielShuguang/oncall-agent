import type { Dispatch, SetStateAction } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { ApprovalScope } from '@/api/approvals';
import type { ApprovalResolveState } from './approvalTypes';

interface Props {
  resolver: ApprovalResolveState | null;
  setResolver: Dispatch<SetStateAction<ApprovalResolveState | null>>;
  onSubmit: () => void;
}

export function ApprovalResolveDialog({ resolver, setResolver, onSubmit }: Props) {
  return (
    <Dialog
      open={resolver !== null}
      onOpenChange={(open) => {
        if (!open && !resolver?.submitting) setResolver(null);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {resolver?.decision === 'approved' ? '批准' : '拒绝'} {resolver?.approval.tool}
          </DialogTitle>
          <DialogDescription>
            发起人 {resolver?.approval.requested_by}；审批后 run 会继续执行或转人工。
          </DialogDescription>
        </DialogHeader>

        <pre className="max-h-48 overflow-auto rounded-md border bg-panel p-3 font-mono text-xs whitespace-pre-wrap">
          {JSON.stringify(resolver?.approval.args ?? {}, null, 2)}
        </pre>

        {resolver?.decision === 'approved' && (
          <div className="text-xs text-muted-foreground">
            授权范围
            <Select
              value={resolver.scope}
              onValueChange={(next) =>
                setResolver((current) =>
                  current ? { ...current, scope: next as ApprovalScope } : current,
                )
              }
            >
              <SelectTrigger className="mt-1 h-8 w-full text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="once">仅本次</SelectItem>
                <SelectItem value="session">本会话同类工具（8 小时）</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        <div>
          <div className="mb-1 text-xs text-muted-foreground">理由（可选）</div>
          <Textarea
            rows={3}
            aria-label="审批理由"
            placeholder={resolver?.decision === 'rejected' ? '建议填写拒绝原因' : '可留空'}
            className="text-xs"
            value={resolver?.reason ?? ''}
            disabled={resolver?.submitting}
            onChange={(event) =>
              setResolver((current) =>
                current ? { ...current, reason: event.target.value } : current,
              )
            }
          />
        </div>

        {resolver?.error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
            {resolver.error}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            disabled={resolver?.submitting}
            onClick={() => setResolver(null)}
          >
            取消
          </Button>
          <Button
            variant={resolver?.decision === 'rejected' ? 'destructive' : 'default'}
            disabled={resolver?.submitting}
            onClick={onSubmit}
          >
            {resolver?.submitting ? '提交中…' : '确认提交'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
