/** 会话侧栏的标题、操作、搜索与列表状态文案。 */

import type { RefObject } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface SessionListChromeProps {
  closeButtonRef: RefObject<HTMLButtonElement | null>;
  searchInputRef: RefObject<HTMLInputElement | null>;
  batchMode: boolean;
  onToggleBatchMode: () => void;
  onNew: () => void;
  onCloseMobile: () => void;
  searchDraft: string;
  onSearchDraftChange: (value: string) => void;
  onSearch: () => void;
  loading: boolean;
  error: string | null;
  query: string;
  sessionCount: number;
  batchNotice: string | null;
  onRetry: () => void;
}

export function SessionListChrome({
  closeButtonRef,
  searchInputRef,
  batchMode,
  onToggleBatchMode,
  onNew,
  onCloseMobile,
  searchDraft,
  onSearchDraftChange,
  onSearch,
  loading,
  error,
  query,
  sessionCount,
  batchNotice,
  onRetry,
}: SessionListChromeProps) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground">会话</span>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={batchMode ? 'secondary' : 'ghost'}
            className="h-7 px-2 text-xs"
            aria-pressed={batchMode}
            onClick={onToggleBatchMode}
          >
            {batchMode ? '完成' : '管理'}
          </Button>
          <Button
            ref={closeButtonRef}
            type="button"
            size="icon"
            variant="ghost"
            className="size-7 sm:hidden"
            aria-label="关闭会话列表"
            onClick={onCloseMobile}
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <Button
        size="sm"
        className="w-full justify-center gap-1.5"
        disabled={batchMode}
        onClick={onNew}
      >
        <Plus className="size-4" />
        新会话
      </Button>

      <form
        className="relative"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          ref={searchInputRef}
          value={searchDraft}
          onChange={(event) => onSearchDraftChange(event.target.value)}
          placeholder="搜索会话标题"
          aria-label="搜索会话标题"
          className="h-9 w-full rounded-lg border bg-canvas/60 pr-2 pl-8 text-xs outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-brand/30 focus-visible:ring-1 focus-visible:ring-brand/20"
        />
      </form>

      {loading && <p className="px-1 py-2 text-xs text-muted-foreground">加载中…</p>}
      {batchNotice && !error && (
        <p className="px-1 py-1 text-xs text-muted-foreground" aria-live="polite">
          {batchNotice}
        </p>
      )}
      {error && (
        <div className="space-y-1 px-1 py-2">
          <p className="text-xs text-danger">{error}</p>
          <Button size="sm" variant="outline" onClick={onRetry}>
            重试
          </Button>
        </div>
      )}
      {!loading && !error && sessionCount === 0 && (
        <p className="px-1 py-2 text-xs text-muted-foreground">
          {query.trim() ? '没有匹配的会话。' : '还没有历史会话。'}
        </p>
      )}
    </>
  );
}
