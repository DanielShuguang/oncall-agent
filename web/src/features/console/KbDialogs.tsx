import type { Dispatch, SetStateAction } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Visibility } from './access';
import type { KbAccessDialogState, KbDetailState } from './kbTypes';

interface Props {
  detail: KbDetailState | null;
  accessDialog: KbAccessDialogState | null;
  setAccessDialog: Dispatch<SetStateAction<KbAccessDialogState | null>>;
  onCloseDetail: () => void;
  onSaveAccess: () => void;
}

export function KbDialogs({
  detail,
  accessDialog,
  setAccessDialog,
  onCloseDetail,
  onSaveAccess,
}: Props) {
  return (
    <>
      <Dialog
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) onCloseDetail();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{detail?.detail?.document.title ?? '切片预览'}</DialogTitle>
            <DialogDescription>
              {detail?.detail ? (
                <>
                  {detail.detail.document.source} · 共 {detail.detail.document.chunk_count} 个切片 ·
                  预览 {detail.detail.chunks.length} 条
                </>
              ) : (
                '正在读取文档切片…'
              )}
            </DialogDescription>
          </DialogHeader>

          {detail?.loading && (
            <div className="py-8 text-center text-xs text-muted-foreground">加载中…</div>
          )}
          {detail?.error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {detail.error}
            </div>
          )}
          {detail?.detail && (
            <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
              {detail.detail.chunks.map((chunk) => (
                <div key={`${chunk.ord}-${chunk.heading ?? ''}`} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">#{chunk.ord}</Badge>
                    <span className="text-xs font-medium">{chunk.heading ?? '（无标题路径）'}</span>
                    {chunk.page !== null && (
                      <span className="text-[11px] text-muted-foreground">第 {chunk.page} 页</span>
                    )}
                  </div>
                  <p className="mt-2 mb-0 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
                    {chunk.content}
                  </p>
                </div>
              ))}
              {detail.detail.chunks.length === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">
                  该文档没有切片。
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={accessDialog !== null}
        onOpenChange={(open) => {
          if (!open) setAccessDialog(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>可见范围</DialogTitle>
            <DialogDescription>
              {accessDialog?.document.title ?? ''} · 只改可见性，不重新切分， 已有引用与{' '}
              <code>chunk_id</code> 不变；保存后立即生效。
            </DialogDescription>
          </DialogHeader>
          {accessDialog && (
            <div className="space-y-3">
              <Select
                value={accessDialog.visibility}
                onValueChange={(value) =>
                  setAccessDialog({
                    ...accessDialog,
                    visibility: value as Visibility,
                    error: null,
                  })
                }
              >
                <SelectTrigger className="w-full" aria-label="可见范围">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="public">公开（所有登录用户）</SelectItem>
                  <SelectItem value="roles">指定角色</SelectItem>
                </SelectContent>
              </Select>
              {accessDialog.visibility === 'roles' && (
                <Input
                  value={accessDialog.rolesText}
                  aria-label="可见角色"
                  placeholder="hr,finance"
                  onChange={(event) =>
                    setAccessDialog({
                      ...accessDialog,
                      rolesText: event.target.value,
                      error: null,
                    })
                  }
                />
              )}
              <p className="mb-0 text-[11px] text-muted-foreground">
                角色是 JWT 里的字符串标签（签发 token 时由部署方决定，如{' '}
                <code>--roles employee,hr</code>）； 拼错会让这篇文档除管理员外谁都看不到。
              </p>
              {accessDialog.error && (
                <div className="rounded-md border border-danger/30 bg-danger/5 p-2 text-xs text-danger">
                  {accessDialog.error}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setAccessDialog(null)}>
                  取消
                </Button>
                <Button size="sm" disabled={accessDialog.saving} onClick={onSaveAccess}>
                  {accessDialog.saving ? '保存中…' : '保存'}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
