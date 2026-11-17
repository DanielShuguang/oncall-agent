import type { RefObject } from 'react';
import { cn } from 'cn';
import { Menu } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { SessionSummary } from '@/api/sessions';
import { PHASE_LABEL } from './chatPhase';

interface Props {
  activeSession: SessionSummary | undefined;
  phase: string;
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
}

export function ChatHeader({ activeSession, phase, drawerOpen, setDrawerOpen, triggerRef }: Props) {
  return (
    <div className="border-b px-4 py-3 sm:px-6">
      <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            ref={triggerRef}
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0 sm:hidden"
            aria-label="打开会话列表"
            aria-controls="session-list"
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(true)}
          >
            <Menu className="size-4" />
          </Button>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{activeSession?.title ?? '新对话'}</h2>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {activeSession
                ? `${activeSession.run_count} 轮对话 · 更新于 ${new Date(activeSession.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
                : '输入问题，开始一轮排查'}
            </p>
          </div>
        </div>
        <Badge
          variant="outline"
          className={cn(
            'shrink-0',
            phase === 'failed'
              ? 'border-danger/30 bg-danger/5 text-danger'
              : phase === 'running'
                ? 'border-brand/30 bg-brand/5 text-brand'
                : 'text-muted-foreground',
          )}
        >
          {PHASE_LABEL[phase] ?? phase}
        </Badge>
      </div>
    </div>
  );
}
