/** 置顶/取消置顶审计（W6 后补）：管理员只读列表、过滤、游标翻页与 CSV 导出（ADR-0085）。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  exportSessionPinAuditsCsv,
  getSessionPinAuditStats,
  listSessionPinAudits,
  type SessionPinAudit,
  type SessionPinAuditFilters,
  type SessionPinAuditStats,
} from '@/api/pinAudits';
import { downloadBlob } from '@/lib/download';
import { PinAuditStatsCard } from './PinAuditStatsCard';
import { PinAuditFilterCard, PinAuditListCard, type PinAuditDraft } from './PinAuditSections';

const PAGE_SIZE = 20;

const EMPTY_DRAFT: PinAuditDraft = {
  userId: '',
  sessionId: '',
  action: 'all',
  from: '',
  to: '',
};

export default function PinAuditPage() {
  const [filters, setFilters] = useState<SessionPinAuditFilters>({});
  const [draft, setDraft] = useState<PinAuditDraft>(EMPTY_DRAFT);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [items, setItems] = useState<SessionPinAudit[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<{ text: string; failed: boolean } | null>(
    null,
  );
  const [statsDays, setStatsDays] = useState<number>(30);
  const [stats, setStats] = useState<SessionPinAuditStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const statsRequest = useRef(0);
  const hasActiveFilters = Boolean(
    filters.userId || filters.sessionId || filters.action || filters.createdFrom,
  );
  // 切换过滤后，旧列表/旧导出都不能再覆盖新结果。
  const listRequest = useRef(0);
  const exportRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++listRequest.current;
    const load = async () => {
      setLoading(true);
      setItems([]);
      setTotal(null);
      setCursor(null);
      setError(null);
      setLoadingMore(false);
      setExportMessage(null);
      try {
        const data = await listSessionPinAudits(filters, null, PAGE_SIZE);
        if (!cancelled && listRequest.current === requestId) {
          setItems(data.items);
          setTotal(data.total ?? null);
          setCursor(data.next_cursor);
        }
      } catch (exc) {
        if (!cancelled && listRequest.current === requestId) {
          setError(exc instanceof Error ? exc.message : '置顶审计加载失败');
        }
      } finally {
        if (!cancelled && listRequest.current === requestId) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
      listRequest.current += 1;
    };
  }, [filters]);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    const load = async () => {
      setStatsLoading(true);
      setStatsError(null);
      setStats(null);
      try {
        const data = await getSessionPinAuditStats(statsDays, filters);
        if (!cancelled && statsRequest.current === requestId) setStats(data);
      } catch (exc) {
        if (!cancelled && statsRequest.current === requestId) {
          setStatsError(exc instanceof Error ? exc.message : '置顶审计统计加载失败');
        }
      } finally {
        if (!cancelled && statsRequest.current === requestId) setStatsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
      statsRequest.current += 1;
    };
  }, [filters, statsDays]);

  const changeStatsDays = (days: number) => {
    if (days === statsDays) return;
    statsRequest.current += 1;
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);
    setStatsDays(days);
  };

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = listRequest.current;
    setLoadingMore(true);
    try {
      const data = await listSessionPinAudits(filters, cursor, PAGE_SIZE);
      if (listRequest.current !== requestId) return;
      setItems((current) => [...current, ...data.items]);
      setCursor(data.next_cursor);
      setError(null);
    } catch (exc) {
      if (listRequest.current === requestId) {
        setError(exc instanceof Error ? exc.message : '加载更多置顶审计失败');
      }
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const applyFilters = () => {
    const userId = draft.userId.trim();
    const sessionId = draft.sessionId.trim();
    if (Boolean(draft.from) !== Boolean(draft.to)) {
      setFilterError('日期范围需要同时填写开始和结束日期。');
      return;
    }
    if (draft.from && draft.to) {
      const from = Date.parse(draft.from);
      const to = Date.parse(draft.to);
      if (Number.isNaN(from) || Number.isNaN(to)) {
        setFilterError('日期格式不正确。');
        return;
      }
      if (from > to) {
        setFilterError('开始日期不能晚于结束日期。');
        return;
      }
      if ((to - from) / 86_400_000 + 1 > 365) {
        setFilterError('日期范围最多 365 天。');
        return;
      }
    }
    setFilterError(null);
    // 立即清空旧行，避免 setFilters 生效前的一帧仍显示旧过滤结果。
    listRequest.current += 1;
    setItems([]);
    setTotal(null);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setExportMessage(null);
    exportRequest.current += 1;
    setExporting(false);
    statsRequest.current += 1;
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);
    setFilters({
      ...(userId ? { userId } : {}),
      ...(sessionId ? { sessionId } : {}),
      ...(draft.action === 'all' ? {} : { action: draft.action }),
      ...(draft.from && draft.to ? { createdFrom: draft.from, createdTo: draft.to } : {}),
    });
  };

  const clearFilters = () => {
    setDraft(EMPTY_DRAFT);
    setFilterError(null);
    listRequest.current += 1;
    setItems([]);
    setTotal(null);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setExportMessage(null);
    exportRequest.current += 1;
    setExporting(false);
    statsRequest.current += 1;
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);
    setFilters({});
  };

  const exportCsv = async () => {
    if (exporting) return;
    const requestId = ++exportRequest.current;
    setExporting(true);
    setExportMessage(null);
    try {
      const result = await exportSessionPinAuditsCsv(filters);
      if (exportRequest.current !== requestId) return;
      downloadBlob(result.blob, 'session-pins.csv');
      setExportMessage({
        failed: false,
        text: result.truncated
          ? `已导出前 ${result.count} 条；超过 5000 条上限，已截断。`
          : `已导出 ${result.count} 条置顶审计。`,
      });
    } catch (exc) {
      if (exportRequest.current !== requestId) return;
      setExportMessage({
        failed: true,
        text: exc instanceof Error ? exc.message : '导出失败',
      });
    } finally {
      if (exportRequest.current === requestId) setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          管理员只读：只记录显式置顶/取消置顶；隐藏会话导致置顶清理不写审计。审计独立保留 365 天，
          导出是同步快照，最多 5000 条。
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={exporting}
          title="按下方已应用的筛选导出"
          onClick={() => void exportCsv()}
        >
          {exporting ? '导出中…' : '导出 CSV'}
        </Button>
      </div>

      {exportMessage && (
        <p className={exportMessage.failed ? 'text-xs text-danger' : 'text-xs text-ok'}>
          {exportMessage.text}
        </p>
      )}

      <PinAuditStatsCard
        stats={stats}
        loading={statsLoading}
        error={statsError}
        days={statsDays}
        filtered={hasActiveFilters}
        dateRangeActive={Boolean(filters.createdFrom && filters.createdTo)}
        onChangeDays={changeStatsDays}
      />

      <PinAuditFilterCard
        draft={draft}
        error={filterError}
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        onApply={applyFilters}
        onClear={clearFilters}
      />

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="flex flex-wrap items-center gap-3 p-3 text-xs text-danger">
            <span className="min-w-0 flex-1">{error}</span>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setFilters((current) => ({ ...current }))}
            >
              重试
            </Button>
          </CardContent>
        </Card>
      )}

      <PinAuditListCard
        items={items}
        total={total}
        cursor={cursor}
        loading={loading}
        loadingMore={loadingMore}
        error={error}
        hasActiveFilters={hasActiveFilters}
        onLoadMore={() => void loadMore()}
      />
    </div>
  );
}
