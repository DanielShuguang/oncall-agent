import { Plus, Send, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { PHASE_LABEL } from './chatPhase';

interface Props {
  text: string;
  setText: (text: string) => void;
  sending: boolean;
  onSend: () => void;
  abort: () => void;
  onNewSession: () => void;
  phase: string;
  historyLoading: boolean;
  costCents: number | null;
}

export function ChatComposer({
  text,
  setText,
  sending,
  onSend,
  abort,
  onNewSession,
  phase,
  historyLoading,
  costCents,
}: Props) {
  return (
    <div className="border-t bg-panel px-4 py-3 sm:px-6">
      <div className="mx-auto w-full max-w-3xl">
        <div className="rounded-xl border bg-panel p-2 shadow-sm ring-1 ring-transparent transition-shadow focus-within:border-brand/30 focus-within:ring-brand/10">
          <Textarea
            value={text}
            rows={1}
            aria-label="消息输入框"
            placeholder="描述你的问题…"
            className="max-h-40 min-h-11 w-full resize-none border-0 bg-transparent px-2 py-2 text-sm shadow-none focus-visible:ring-0"
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
          />
          <div className="mt-1 flex items-center justify-between gap-2 px-1">
            <span className="hidden text-[11px] text-muted-foreground sm:inline">
              Enter 发送 · Shift+Enter 换行
            </span>
            <div className="ml-auto flex items-center gap-1.5">
              <Button
                size="icon"
                variant="ghost"
                className="size-8 text-muted-foreground"
                aria-label="新会话"
                disabled={sending}
                onClick={onNewSession}
              >
                <Plus className="size-4" />
              </Button>
              {sending ? (
                <Button size="sm" variant="destructive" onClick={abort}>
                  <Square className="size-3.5 fill-current" />
                  停止
                </Button>
              ) : (
                <Button size="sm" onClick={onSend} disabled={!text.trim()}>
                  <Send className="size-3.5" />
                  发送
                </Button>
              )}
            </div>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
          <span>
            状态：{PHASE_LABEL[phase] ?? phase}
            {historyLoading ? ' · 历史会话加载中…' : ''}
          </span>
          <span>{costCents !== null ? `本轮成本 ¥${(costCents / 100).toFixed(2)}` : ''}</span>
        </div>
      </div>
    </div>
  );
}
