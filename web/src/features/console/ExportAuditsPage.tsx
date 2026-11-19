/** CSV 导出下载审计（ADR-0094）。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  EXPORT_RESOURCE_LABEL,
  listExportAudits,
  type ExportAudit,
  type ExportAuditFilters,
  type ExportResource,
} from '@/api/exportAudits';
import { formatTime } from '@/lib/format';
import { useExportAuditExport } from './useExportAuditExport';

const EMPTY_DRAFT = {
  userId: '',
  resource: '' as '' | ExportResource,
  createdFrom: '',
  createdTo: '',
};

type Draft = typeof EMPTY_DRAFT;

function hasFilters(filters: ExportAuditFilters): boolean {
  return Boolean(filters.userId || filters.resource || filters.createdFrom || filters.createdTo);
}

function filterText(filters: Record<string, string>): string {
  const entries = Object.entries(filters);
  if (entries.length === 0) return '—';
  return entries.map(([key, value]) => `${key}=${value}`).join(' · ');
}

export default function ExportAuditsPage() {
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [filters, setFilters] = useState<ExportAuditFilters>({});
  const [items, setItems] = useState<ExportAudit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const requestRef = useRef(0);
  const exports = useExportAuditExport(filters, () => setFilters({ ...filters }));

  useEffect(() => {
    let cancelled = false;
    const request = ++requestRef.current;
    const load = async () => {
      setLoading(true);
      setLoadingMore(false);
      setError(null);
      try {
        const page = await listExportAudits(filters);
        if (cancelled || request !== requestRef.current) return;
        setItems(page.items);
        setCursor(page.next_cursor);
        setTotal(page.total ?? null);
      } catch (caught) {
        if (!cancelled && request === requestRef.current) {
          setError(caught instanceof Error ? caught.message : '加载失败');
        }
      } finally {
        if (!cancelled && request === requestRef.current) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [filters]);

  const applyFilters = () => {
    if (Boolean(draft.createdFrom) !== Boolean(draft.createdTo)) {
      setFilterError('开始日期与结束日期必须同时选择');
      return;
    }
    setFilterError(null);
    requestRef.current += 1;
    setItems([]);
    setCursor(null);
    setTotal(null);
    setFilters({
      userId: draft.userId.trim() || undefined,
      resource: draft.resource || undefined,
      createdFrom: draft.createdFrom || undefined,
      createdTo: draft.createdTo || undefined,
    });
  };

  const clearFilters = () => {
    setFilterError(null);
    requestRef.current += 1;
    setDraft(EMPTY_DRAFT);
    setItems([]);
    setCursor(null);
    setTotal(null);
    setFilters({});
  };

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const request = requestRef.current;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await listExportAudits(filters, cursor);
      if (request !== requestRef.current) return;
      setItems((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      if (request === requestRef.current) {
        setError(caught instanceof Error ? caught.message : '加载更多失败');
      }
    } finally {
      if (request === requestRef.current) setLoadingMore(false);
    }
  };

  return (
    <div className="space-y-3">
      <Card className="gap-0 py-0">
        <CardContent className="flex flex-wrap items-end gap-2 p-3">
          <div className="min-w-40 flex-1">
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-user">
              用户
            </label>
            <Input
              id="export-user"
              className="h-8 text-xs"
              placeholder="如 u_102"
              value={draft.userId}
              onChange={(event) => setDraft({ ...draft, userId: event.target.value })}
            />
          </div>
          <div className="min-w-40">
            <label
              className="mb-1 block text-[11px] text-muted-foreground"
              htmlFor="export-resource"
            >
              资源
            </label>
            <select
              id="export-resource"
              className="h-8 w-full rounded-md border bg-panel px-2 text-xs"
              value={draft.resource}
              onChange={(event) =>
                setDraft({ ...draft, resource: event.target.value as '' | ExportResource })
              }
            >
              <option value="">全部资源</option>
              {(Object.keys(EXPORT_RESOURCE_LABEL) as ExportResource[]).map((resource) => (
                <option key={resource} value={resource}>
                  {EXPORT_RESOURCE_LABEL[resource]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-from">
              起（UTC）
            </label>
            <Input
              id="export-from"
              type="date"
              className="h-8 w-36 text-xs"
              value={draft.createdFrom}
              onChange={(event) => setDraft({ ...draft, createdFrom: event.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-to">
              止（UTC）
            </label>
            <Input
              id="export-to"
              type="date"
              className="h-8 w-36 text-xs"
              value={draft.createdTo}
              onChange={(event) => setDraft({ ...draft, createdTo: event.target.value })}
            />
          </div>
          <Button size="sm" className="h-8 text-xs" onClick={applyFilters}>
            筛选
          </Button>
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={clearFilters}>
            清除
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            disabled={exports.exporting}
            onClick={() => void exports.exportCsv()}
          >
            {exports.exporting ? '导出中…' : '导出 CSV'}
          </Button>
          {filterError && <span className="text-xs text-danger">{filterError}</span>}
        </CardContent>
        {exports.message && <p className="text-xs text-muted-foreground">{exports.message}</p>}
      </Card>

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="flex flex-wrap items-center gap-3 p-3 text-xs text-danger">
            <span className="min-w-0 flex-1">{error}</span>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setFilters({ ...filters })}
            >
              重试
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          {!loading && items.length > 0 && (
            <div className="border-b px-3 py-2 text-[11px] text-muted-foreground">
              {total !== null && total > 0
                ? `共 ${total} 条${hasFilters(filters) ? '（当前筛选）' : ''}${
                    items.length < total ? `，已加载 ${items.length} 条` : ''
                  }`
                : `已加载 ${items.length} 条${hasFilters(filters) ? '（当前筛选）' : ''}`}
            </div>
          )}
          {loading ? (
            <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-xs text-muted-foreground">
              {hasFilters(filters) ? '没有符合筛选条件的导出记录。' : '还没有导出审计记录。'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>导出时间</TableHead>
                    <TableHead>操作人</TableHead>
                    <TableHead>资源</TableHead>
                    <TableHead>行数</TableHead>
                    <TableHead>过滤条件</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="align-top text-xs whitespace-nowrap text-muted-foreground">
                        {formatTime(item.created_at)}
                      </TableCell>
                      <TableCell className="align-top font-mono text-xs">{item.user_id}</TableCell>
                      <TableCell className="align-top text-xs whitespace-nowrap">
                        {EXPORT_RESOURCE_LABEL[item.resource] ?? item.resource}
                      </TableCell>
                      <TableCell className="align-top text-xs whitespace-nowrap">
                        {item.row_count}
                        {item.truncated && <span className="ml-1 text-warn">（截断）</span>}
                      </TableCell>
                      <TableCell className="max-w-xl align-top font-mono text-[11px] break-all text-muted-foreground">
                        {filterText(item.filters)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {!loading && cursor && (
            <div className="border-t p-3 text-center">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                disabled={loadingMore}
                onClick={() => void loadMore()}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
