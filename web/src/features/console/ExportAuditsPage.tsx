/** CSV 导出下载审计（ADR-0094）。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
} from '@/api/exportAudits';
import { formatTime } from '@/lib/format';
import {
  activeAuditDatePreset,
  auditDatePresetRange,
  clearAuditDatePresetFor,
  EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY,
  readAuditDatePresetFor,
  writeAuditDatePresetFor,
  type AuditDatePreset,
} from './auditDatePresets';
import { ExportAuditFilterBar } from './ExportAuditFilterBar';
import {
  EMPTY_EXPORT_AUDIT_DRAFT,
  toExportAuditFilters,
  type ExportAuditDraft,
} from './exportAuditDraft';
import { useExportAuditExport } from './useExportAuditExport';

function hasFilters(filters: ExportAuditFilters): boolean {
  return Boolean(filters.userId || filters.resource || filters.createdFrom || filters.createdTo);
}

function filterText(filters: Record<string, string>): string {
  const entries = Object.entries(filters);
  if (entries.length === 0) return '—';
  return entries.map(([key, value]) => `${key}=${value}`).join(' · ');
}

function initialExportAuditState(): {
  draft: ExportAuditDraft;
  filters: ExportAuditFilters;
} {
  const preset = readAuditDatePresetFor(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY);
  if (!preset) return { draft: EMPTY_EXPORT_AUDIT_DRAFT, filters: {} };
  const range = auditDatePresetRange(preset);
  return {
    draft: { ...EMPTY_EXPORT_AUDIT_DRAFT, createdFrom: range.from, createdTo: range.to },
    filters: { createdFrom: range.from, createdTo: range.to },
  };
}
export default function ExportAuditsPage() {
  const [initial] = useState(initialExportAuditState);
  const [draft, setDraft] = useState<ExportAuditDraft>(initial.draft);
  const [filters, setFilters] = useState<ExportAuditFilters>(initial.filters);
  const [items, setItems] = useState<ExportAudit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const requestRef = useRef(0);
  const exports = useExportAuditExport(filters, () => setFilters((current) => ({ ...current })));

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

  const commitFilters = (next: ExportAuditDraft) => {
    if (Boolean(next.createdFrom) !== Boolean(next.createdTo)) {
      setFilterError('开始日期与结束日期必须同时选择');
      return;
    }
    setFilterError(null);
    const preset =
      next.createdFrom && next.createdTo
        ? activeAuditDatePreset(next.createdFrom, next.createdTo)
        : null;
    if (preset) writeAuditDatePresetFor(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY, preset);
    else clearAuditDatePresetFor(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY);
    exports.invalidate();
    requestRef.current += 1;
    setItems([]);
    setCursor(null);
    setTotal(null);
    setFilters(toExportAuditFilters(next));
  };

  const applyFilters = () => commitFilters(draft);

  const applyPreset = (preset: AuditDatePreset) => {
    const next = { ...draft, ...auditDatePresetRange(preset) };
    setDraft(next);
    commitFilters(next);
  };

  const clearFilters = () => {
    clearAuditDatePresetFor(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY);
    setFilterError(null);
    exports.invalidate();
    requestRef.current += 1;
    setDraft(EMPTY_EXPORT_AUDIT_DRAFT);
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

  const activePreset = activeAuditDatePreset(filters.createdFrom ?? '', filters.createdTo ?? '');

  return (
    <div className="space-y-3">
      <ExportAuditFilterBar
        activePreset={activePreset}
        draft={draft}
        exportMessage={exports.message}
        exporting={exports.exporting}
        filterError={filterError}
        onApply={applyFilters}
        onChange={setDraft}
        onClear={clearFilters}
        onExport={() => void exports.exportCsv()}
        onPreset={applyPreset}
      />

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
                        {item.content_sha256 && (
                          <div
                            className="mt-1 font-mono text-[10px] text-muted-foreground"
                            title={item.content_sha256}
                          >
                            {item.content_sha256.slice(0, 12)}…
                          </div>
                        )}
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
