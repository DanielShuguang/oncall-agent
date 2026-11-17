/** 会话列表的单个行：普通、批量、重命名与移除确认（ADR-0030/0041/0069/0072）。 */

import { MessageSquare, Pencil, Pin, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { SessionSummary } from '@/api/sessions';
import { cn } from 'cn';
import { formatUpdated } from './sessionFormat';

interface SessionListItemProps {
  session: SessionSummary;
  active: boolean;
  batchMode: boolean;
  batchSelected: boolean;
  batchHiding: boolean;
  busy: boolean;
  renaming: boolean;
  renameDraft: string;
  renameSaving: boolean;
  confirming: boolean;
  hidingId: string | null;
  pinningId: string | null;
  pinLimitReached: boolean;
  pinLimit: number | null;
  onBatchToggleSelect: (sessionId: string) => void;
  onSelect: () => void;
  onTogglePin: () => void;
  onRenameStart: () => void;
  onRenameDraftChange: (value: string) => void;
  onRenameSubmit: () => void;
  onRenameCancel: () => void;
  onConfirmRemove: () => void;
  onCancelRemove: () => void;
  onHide: () => void;
}

export function SessionListItem({
  session,
  active,
  batchMode,
  batchSelected,
  batchHiding,
  busy,
  renaming,
  renameDraft,
  renameSaving,
  confirming,
  hidingId,
  pinningId,
  pinLimitReached,
  pinLimit,
  onBatchToggleSelect,
  onSelect,
  onTogglePin,
  onRenameStart,
  onRenameDraftChange,
  onRenameSubmit,
  onRenameCancel,
  onConfirmRemove,
  onCancelRemove,
  onHide,
}: SessionListItemProps) {
  if (batchMode) {
    return (
      <label
        className={cn(
          'flex cursor-pointer items-start gap-2 rounded-xl border bg-canvas/60 p-2.5 text-xs transition-colors',
          batchSelected && 'border-brand/30 bg-brand/5',
        )}
      >
        <input
          type="checkbox"
          className="mt-0.5 accent-brand"
          checked={batchSelected}
          onChange={() => onBatchToggleSelect(session.session_id)}
          disabled={batchHiding}
          aria-label={`选择会话 ${session.title ?? '无标题'}`}
        />
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 wrap-break-word text-[13px] font-medium">
            {session.title ?? '无标题'}
          </span>
          <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
            <MessageSquare className="size-3" />
            {session.run_count} 轮 · {formatUpdated(session.updated_at)}
          </span>
        </span>
      </label>
    );
  }

  if (renaming) {
    return (
      <form
        className="flex flex-col gap-1.5 rounded-xl border bg-panel p-2 shadow-sm"
        onSubmit={(event) => {
          event.preventDefault();
          onRenameSubmit();
        }}
      >
        <input
          value={renameDraft}
          maxLength={60}
          disabled={renameSaving}
          onChange={(event) => onRenameDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              onRenameCancel();
            }
          }}
          aria-label="会话标题"
          placeholder="最多 60 字，留空恢复默认"
          className="h-8 w-full rounded-md border bg-transparent px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-brand/40"
        />
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="outline" type="button" onClick={onRenameCancel}>
            取消
          </Button>
          <Button size="sm" type="submit" disabled={busy || renameSaving}>
            {renameSaving ? '保存中…' : '保存'}
          </Button>
        </div>
      </form>
    );
  }

  if (confirming) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-danger/30 bg-danger/5 p-2.5">
        <p className="text-xs leading-5 text-muted-foreground">
          从列表移除「{session.title ?? '无标题'}」？run 与审批仍按保留期保存。
        </p>
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="outline" type="button" onClick={onCancelRemove}>
            取消
          </Button>
          <Button
            size="sm"
            variant="destructive"
            type="button"
            disabled={hidingId === session.session_id}
            onClick={onHide}
          >
            {hidingId === session.session_id ? '移除中…' : '移除'}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative">
      <div
        className={cn(
          'rounded-xl border border-transparent transition-colors',
          active ? 'border-brand/20 bg-brand/5' : 'hover:bg-canvas',
        )}
      >
        <button
          type="button"
          aria-current={active ? 'true' : undefined}
          disabled={busy}
          className="w-full min-w-0 rounded-xl px-3 py-2.5 pr-24 text-left disabled:cursor-default disabled:opacity-60"
          onClick={onSelect}
        >
          <span className="flex items-center gap-1.5">
            {session.pinned && <Pin className="size-3 shrink-0 fill-current text-brand" />}
            <span className="truncate text-[13px] font-medium">{session.title ?? '无标题'}</span>
          </span>
          <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
            <MessageSquare className="size-3" />
            {session.run_count} 轮<span className="px-0.5">·</span>
            {formatUpdated(session.updated_at)}
          </span>
        </button>
        <div
          className={cn(
            'absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-0.5 rounded-md bg-panel/95 p-0.5 shadow-sm ring-1 ring-line/60 transition-opacity',
            active
              ? 'opacity-100'
              : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100',
          )}
        >
          {session.pinned !== undefined && (
            <Button
              size="icon"
              variant="ghost"
              className={cn('size-6 text-muted-foreground', session.pinned && 'text-brand')}
              aria-label={`${session.pinned ? '取消置顶' : '置顶'}会话 ${session.title ?? '无标题'}`}
              aria-pressed={session.pinned}
              title={
                !session.pinned && pinLimitReached
                  ? `置顶数量已达上限（${pinLimit} 个）`
                  : undefined
              }
              disabled={busy || pinningId !== null || (!session.pinned && pinLimitReached)}
              onClick={onTogglePin}
            >
              <Pin className={cn('size-3.5', session.pinned && 'fill-current')} />
            </Button>
          )}
          <Button
            size="icon"
            variant="ghost"
            className="size-6 text-muted-foreground"
            aria-label={`重命名会话 ${session.title ?? '无标题'}`}
            disabled={busy}
            onClick={onRenameStart}
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-6 text-muted-foreground hover:text-danger"
            aria-label={`从列表移除会话 ${session.title ?? '无标题'}`}
            disabled={busy || hidingId !== null}
            onClick={onConfirmRemove}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
