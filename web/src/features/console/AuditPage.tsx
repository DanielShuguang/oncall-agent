/** 会话恢复审计（W6 后补）：管理端只读列表、过滤、翻页、首屏总数、统计与 CSV 导出（ADR-0063/0064/0065/0067/0075/0078）。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  getSessionRestoreAuditStats,
  listSessionRestoreAudits,
  type SessionRestoreAudit,
  type SessionRestoreAuditFilters,
  type SessionRestoreAuditStats,
} from '@/api/sessionAudits';
import {
  auditDatePresetRange,
  clearLastAuditDatePreset,
  writeLastAuditDatePreset,
  type AuditDatePreset,
} from './auditDatePresets';
import { readInitialAuditState } from './auditInitialState';
import {
  clearAuditFilterMemory,
  writeAuditFilterMemory,
  type AuditStatsDays,
} from './auditFilterMemory';
import { AuditFilterCard } from './AuditFilterCard';
import { AuditStatsCard } from './AuditStatsCard';
import { AuditTableCard } from './AuditTableCard';
import { useAuditExports } from './useAuditExports';

const PAGE_SIZE = 20;

export default function AuditPage() {
  const [items, setItems] = useState<SessionRestoreAudit[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [stats, setStats] = useState<SessionRestoreAuditStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [initialAuditState] = useState(readInitialAuditState);
  const [statsDays, setStatsDays] = useState<AuditStatsDays>(initialAuditState.statsDays);
  const [activePreset, setActivePreset] = useState<AuditDatePreset | null>(
    initialAuditState.preset,
  );
  const [filters, setFilters] = useState<SessionRestoreAuditFilters>(initialAuditState.filters);
  const [filterUserId, setFilterUserId] = useState(initialAuditState.userId);
  const [filterSessionId, setFilterSessionId] = useState(initialAuditState.sessionId);
  const [filterFrom, setFilterFrom] = useState(initialAuditState.range?.from ?? '');
  const [filterTo, setFilterTo] = useState(initialAuditState.range?.to ?? '');
  const [filterError, setFilterError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasDateRange = Boolean(filters.restoredFrom && filters.restoredTo);
  const hasActiveFilters = Boolean(filters.userId || filters.sessionId || hasDateRange);
  // 切过滤/重试后在途请求不能覆盖新列表；统计同理。
  const listRequest = useRef(0);
  const statsRequest = useRef(0);
  const {
    exporting,
    exportMessage,
    statsExporting,
    statsExportMessage,
    exportCsv,
    exportStats,
    invalidate: invalidateExports,
  } = useAuditExports(filters, statsDays, hasDateRange, stats);

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
      try {
        const data = await listSessionRestoreAudits(filters, null, PAGE_SIZE);
        if (!cancelled && listRequest.current === requestId) {
          setItems(data.items);
          setCursor(data.next_cursor);
          setTotal(data.total ?? null);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled && listRequest.current === requestId) {
          setError(exc instanceof Error ? exc.message : '恢复审计加载失败');
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
      try {
        const data = await getSessionRestoreAuditStats(statsDays, filters);
        if (!cancelled && statsRequest.current === requestId) setStats(data);
      } catch (exc) {
        if (!cancelled && statsRequest.current === requestId) {
          setStatsError(exc instanceof Error ? exc.message : '统计加载失败');
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
  }, [statsDays, filters]);

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = listRequest.current;
    setLoadingMore(true);
    try {
      const data = await listSessionRestoreAudits(filters, cursor, PAGE_SIZE);
      if (listRequest.current !== requestId) return;
      setItems((current) => [...current, ...data.items]);
      setCursor(data.next_cursor);
      setError(null);
    } catch (exc) {
      if (listRequest.current === requestId) {
        setError(exc instanceof Error ? exc.message : '加载更多恢复审计失败');
      }
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const resetForFilters = () => {
    // 立即失效旧列表/旧导出/旧统计，避免 setFilters 生效前的一帧里旧数据
    // 显示在新过滤条件下。
    listRequest.current += 1;
    setItems([]);
    setTotal(null);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    statsRequest.current += 1;
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);
    invalidateExports();
  };

  const changeStatsDays = (days: AuditStatsDays) => {
    if (days === statsDays) return;
    // 切换窗口时立即清掉旧窗口统计；effect 随后会按新窗口重新请求。
    statsRequest.current += 1;
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);
    invalidateExports();
    setStatsDays(days);
    writeAuditFilterMemory({
      userId: filters.userId ?? '',
      sessionId: filters.sessionId ?? '',
      statsDays: days,
    });
  };

  const applyFilters = (
    dates?: { from: string; to: string },
    preset: AuditDatePreset | null = null,
  ) => {
    const userId = filterUserId.trim();
    const sessionId = filterSessionId.trim();
    const restoredFrom = dates?.from ?? filterFrom.trim();
    const restoredTo = dates?.to ?? filterTo.trim();
    if (Boolean(restoredFrom) !== Boolean(restoredTo)) {
      setFilterError('开始日期与结束日期必须同时选择');
      return;
    }
    if (restoredFrom && restoredTo && restoredFrom > restoredTo) {
      setFilterError('开始日期不能晚于结束日期');
      return;
    }
    setFilterError(null);
    const activePresetRange = activePreset ? auditDatePresetRange(activePreset) : null;
    const keepsActivePreset =
      !preset &&
      activePresetRange !== null &&
      restoredFrom === activePresetRange.from &&
      restoredTo === activePresetRange.to;
    if (preset) {
      writeLastAuditDatePreset(preset);
    } else if (!keepsActivePreset) {
      // 只记住预设；手填日期或清空日期时不持久化，避免下次落到过期窗口。
      clearLastAuditDatePreset();
    }
    setActivePreset(preset ?? (keepsActivePreset ? activePreset : null));
    resetForFilters();
    const nextFilters: SessionRestoreAuditFilters = {
      ...(userId ? { userId } : {}),
      ...(sessionId ? { sessionId } : {}),
      ...(restoredFrom && restoredTo ? { restoredFrom, restoredTo } : {}),
    };
    setFilters(nextFilters);
    writeAuditFilterMemory({
      userId: nextFilters.userId ?? '',
      sessionId: nextFilters.sessionId ?? '',
      statsDays,
    });
  };

  const applyDatePreset = (preset: AuditDatePreset) => {
    const range = auditDatePresetRange(preset);
    setFilterFrom(range.from);
    setFilterTo(range.to);
    applyFilters(range, preset);
  };

  const clearFilters = () => {
    clearLastAuditDatePreset();
    clearAuditFilterMemory();
    setActivePreset(null);
    resetForFilters();
    setFilterUserId('');
    setFilterSessionId('');
    setFilterFrom('');
    setFilterTo('');
    setFilterError(null);
    setFilters({});
    // 统计窗口也属于记住的过滤偏好；清除后回到默认 30 天，避免当前 7 天与下次打开的 30 天不一致。
    setStatsDays(30);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          管理员只读：每次恢复操作一行，只记录真正恢复的会话；审计独立保留 365 天。
          导出是同步快照，最多 5000 条。
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={exporting}
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

      <AuditStatsCard
        stats={stats}
        loading={statsLoading}
        error={statsError}
        days={statsDays}
        hasDateRange={hasDateRange}
        filters={filters}
        exporting={statsExporting}
        message={statsExportMessage}
        onChangeDays={changeStatsDays}
        onExport={() => void exportStats()}
      />

      <AuditFilterCard
        userId={filterUserId}
        sessionId={filterSessionId}
        from={filterFrom}
        to={filterTo}
        activePreset={activePreset}
        error={filterError}
        onChangeUserId={setFilterUserId}
        onChangeSessionId={setFilterSessionId}
        onChangeFrom={setFilterFrom}
        onChangeTo={setFilterTo}
        onApplyPreset={applyDatePreset}
        onApply={() => applyFilters()}
        onClear={clearFilters}
      />

      <AuditTableCard
        items={items}
        total={total}
        hasActiveFilters={hasActiveFilters}
        loading={loading}
        loadingMore={loadingMore}
        cursor={cursor}
        error={error}
        onRetry={() => setFilters((current) => ({ ...current }))}
        onLoadMore={() => void loadMore()}
      />
    </div>
  );
}
