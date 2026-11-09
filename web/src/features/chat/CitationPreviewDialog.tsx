import { useEffect, useRef, useState } from 'react';
import { getKbPreview, type KbPreview } from '@/api/kb';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { describePreview } from './citation';
import type { Citation } from './types';

/** 结果里带 key：换一条引用时旧结果不能顶替新引用的加载态。 */
type PreviewState =
  | { key: string; phase: 'ready'; preview: KbPreview }
  | { key: string; phase: 'error'; message: string };

interface Props {
  citation: Citation | null;
  onClose: () => void;
}

/**
 * 引用跳全文：按切片顺序展示整篇文档，并把引用段滚到视野中央。
 *
 * 加载失败时退回引用片段，而不是空白弹窗——片段本来就在事件里，
 * 没有理由因为一次预览请求失败就什么都不给。
 */
export function CitationPreviewDialog({ citation, onClose }: Props) {
  const [state, setState] = useState<PreviewState | null>(null);
  const [attempt, setAttempt] = useState(0);
  const focusRef = useRef<HTMLDivElement | null>(null);
  const documentId = citation?.document_id ?? null;
  const chunkId = citation?.chunk_id;
  const ord = citation?.ord;
  // attempt 进 key：点重试时回到加载态，而不是让旧错误继续顶在那里
  const key = citation ? `${citation.document_id}:${citation.chunk_id}:${attempt}` : null;

  // 派生而不是在 effect 里同步 setState：换引用时 key 变了，自然回到加载态
  const ready = state?.phase === 'ready' && state.key === key ? state.preview : null;
  const error = state?.phase === 'error' && state.key === key ? state.message : null;
  const loading = key !== null && ready === null && error === null;

  useEffect(() => {
    if (documentId === null || key === null) return;
    let cancelled = false;
    const load = async () => {
      try {
        const preview = await getKbPreview(documentId, { chunkId, ord });
        if (!cancelled) setState({ key, phase: 'ready', preview });
      } catch (exc) {
        if (!cancelled) {
          setState({
            key,
            phase: 'error',
            message: exc instanceof Error ? exc.message : '全文预览加载失败',
          });
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [documentId, chunkId, ord, key]);

  useEffect(() => {
    if (ready === null) return;
    focusRef.current?.scrollIntoView({ block: 'center' });
  }, [ready]);

  return (
    <Dialog
      open={citation !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{citation?.title ?? '知识库原文'}</DialogTitle>
          <DialogDescription>
            {citation?.heading ?? '知识库原文'}
            {citation?.page ? ` · 第 ${citation.page} 页` : ''}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div aria-busy="true" className="space-y-2 py-6">
            <div className="h-4 w-2/3 animate-pulse rounded bg-canvas" />
            <div className="h-4 animate-pulse rounded bg-canvas" />
            <div className="h-4 w-5/6 animate-pulse rounded bg-canvas" />
          </div>
        )}

        {error !== null && (
          <div className="space-y-2">
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              全文预览加载失败：{error}
            </div>
            <div className="rounded-md border bg-panel p-3 text-sm leading-relaxed whitespace-pre-wrap">
              {citation?.snippet}
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">以上是引用片段，不是全文。</p>
              <Button variant="outline" size="sm" onClick={() => setAttempt((value) => value + 1)}>
                重试
              </Button>
            </div>
          </div>
        )}

        {ready !== null && (
          <>
            <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
              {ready.chunks.map((chunk, index) => {
                const previousHeading = index > 0 ? ready.chunks[index - 1]?.heading : null;
                const showHeading = chunk.heading !== null && chunk.heading !== previousHeading;
                const focused = chunk.chunk_id === ready.focused_chunk_id;
                return (
                  <div
                    key={chunk.chunk_id}
                    ref={focused ? focusRef : undefined}
                    className={
                      focused
                        ? 'rounded-md border border-brand/40 bg-brand/5 p-3'
                        : 'rounded-md border border-transparent px-3 py-2'
                    }
                  >
                    {(showHeading || focused) && (
                      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {showHeading && <span className="font-medium">{chunk.heading}</span>}
                        {chunk.page !== null && <span>第 {chunk.page} 页</span>}
                        {focused && <Badge variant="outline">引用位置</Badge>}
                      </div>
                    )}
                    <p className="mb-0 text-sm leading-relaxed whitespace-pre-wrap">
                      {chunk.content}
                    </p>
                  </div>
                );
              })}
              {ready.chunks.length === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">
                  该文档没有可预览的切片。
                </div>
              )}
            </div>
            {citation && (
              <p className="text-xs text-muted-foreground">
                {describePreview(ready, citation)} · 来源 {ready.document.source} ·
                按切片重组，与原始文件排版不完全一致
              </p>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
