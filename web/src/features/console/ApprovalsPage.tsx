/** 审批中心（W5 D23）：待办 / 已办可筛，审批人才能决议。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  listApprovals,
  resolveApproval,
  type ApprovalDecision,
  type ApprovalListFilters,
  type ApprovalOut,
} from '@/api/approvals';
import { ApprovalFilterCard } from './ApprovalFilterCard';
import { filtersAfterStatusChange, writeApprovalFilterMemory } from './approvalFilterMemory';
import { ApprovalResolveDialog } from './ApprovalResolveDialog';
import { ApprovalStatsPanel } from './ApprovalStatsPanel';
import { ApprovalTableCard } from './ApprovalTableCard';
import type { ApprovalResolveState, StatsGroup } from './approvalTypes';
import { useApprovalExports } from './useApprovalExports';
import { useApprovalStats } from './useApprovalStats';
import { readApprovalStatsGroup, writeApprovalStatsGroup } from './approvalStatsGroup';
import { readApprovalStatsWindow, writeApprovalStatsWindow } from './approvalStatsWindow';

const STATUS_OPTIONS = [
  { value: 'pending', label: '待办' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'expired', label: '已过期' },
];

export default function ApprovalsPage() {
  const [status, setStatus] = useState('pending');
  const [items, setItems] = useState<ApprovalOut[]>([]);
  const [filters, setFilters] = useState<ApprovalListFilters>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resolver, setResolver] = useState<ApprovalResolveState | null>(null);
  const [statsDays, setStatsDays] = useState<number>(readApprovalStatsWindow);
  const [statsGroup, setStatsGroup] = useState<StatsGroup>(readApprovalStatsGroup);
  const hasActiveFilters = Object.keys(filters).length > 0;
  // 列表分页存在竞态：切状态/刷新后在途的「加载更多」不能把旧页追加回来。
  const listRequest = useRef(0);
  const {
    stats,
    statsGroupView,
    lastUpdatedAt,
    refreshing,
    autoRefreshEnabled,
    autoRefreshError,
    refreshIntervalSec,
    setAutoRefresh,
    setRefreshInterval,
    refresh: refreshStats,
  } = useApprovalStats(statsDays, statsGroup);
  const exports = useApprovalExports(status, filters, statsDays, statsGroup);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++listRequest.current;
    const load = async () => {
      setLoading(true);
      setCursor(null);
      setLoadingMore(false);
      try {
        const data = await listApprovals(status, null, 50, filters);
        if (!cancelled && listRequest.current === requestId) {
          setItems(data.items);
          setCursor(data.next_cursor);
          setTotal(data.total ?? null);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled && listRequest.current === requestId) {
          setError(exc instanceof Error ? exc.message : '审批列表加载失败');
        }
      } finally {
        if (!cancelled && listRequest.current === requestId) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
      // 卸载/切状态后，在途的 refresh/loadMore 也不得再改新列表。
      listRequest.current += 1;
    };
  }, [status, filters]);

  const refresh = async () => {
    const requestId = ++listRequest.current;
    // 刷新期间禁用「加载更多」，也避免它被旧游标带到新列表里。
    setLoadingMore(true);
    try {
      const data = await listApprovals(status, null, 50, filters);
      if (listRequest.current !== requestId) return;
      setItems(data.items);
      setCursor(data.next_cursor);
      setTotal(data.total ?? null);
      setError(null);
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = listRequest.current;
    setLoadingMore(true);
    try {
      const data = await listApprovals(status, cursor, 50, filters);
      if (listRequest.current !== requestId) return;
      setItems((current) => [...current, ...data.items]);
      setCursor(data.next_cursor);
      setError(null);
    } catch (exc) {
      if (listRequest.current === requestId) {
        setError(exc instanceof Error ? exc.message : '加载更多审批失败');
      }
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const resetList = (next: ApprovalListFilters) => {
    listRequest.current += 1;
    setItems([]);
    setCursor(null);
    setTotal(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setNotice(null);
    exports.invalidateList();
    writeApprovalFilterMemory(next);
    setFilters(next);
  };

  const changeStatus = (next: string) => {
    // 先让在途请求失效并清空旧列表：否则切到已办时，上一帧仍会渲染待办行，
    // 且表头已变成「决议时间」（ADR-0053）。
    // 待办不显示筛选；切回已办时恢复上次记住的已办筛选（ADR-0135）。
    const nextFilters = filtersAfterStatusChange(next, status, filters);
    listRequest.current += 1;
    setStatus(next);
    setItems([]);
    setCursor(null);
    setTotal(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setNotice(null);
    exports.invalidateList();
    setFilters(nextFilters);
  };

  const changeStatsDays = (days: number) => {
    if (days === statsDays) return;
    exports.invalidateStats();
    setStatsDays(days);
    writeApprovalStatsWindow(days);
  };

  const changeStatsGroup = (next: StatsGroup) => {
    if (next === statsGroup) return;
    exports.invalidateStats();
    setStatsGroup(next);
    writeApprovalStatsGroup(next);
  };

  const openResolve = (approval: ApprovalOut, decision: ApprovalDecision) => {
    setResolver({ approval, decision, reason: '', scope: 'once', submitting: false, error: null });
  };

  const submit = async () => {
    if (!resolver) return;
    setResolver({ ...resolver, submitting: true, error: null });
    try {
      const result = await resolveApproval(resolver.approval.approval_id, resolver.decision, {
        reason: resolver.reason.trim() || undefined,
        scope: resolver.decision === 'approved' ? resolver.scope : 'once',
      });
      setResolver(null);
      setNotice(
        `${resolver.decision === 'approved' ? '已批准' : '已拒绝'} ${
          resolver.approval.tool
        }；run 当前状态：${result.run_status ?? '未知'}。`,
      );
      try {
        await refresh();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : '决议已提交，但列表刷新失败');
      }
      await refreshStats();
    } catch (exc) {
      setResolver((current) =>
        current
          ? {
              ...current,
              submitting: false,
              error: exc instanceof Error ? exc.message : '提交失败',
            }
          : current,
      );
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          审批人看到全部待办，普通员工只看到自己发起的；通过后从快照恢复 <code>act</code>，
          拒绝后不执行写工具。
        </div>
        <Select value={status} onValueChange={changeStatus}>
          <SelectTrigger className="h-8 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={exports.exporting}
          onClick={() => void exports.exportCsv()}
        >
          {exports.exporting ? '导出中…' : '导出 CSV'}
        </Button>
      </div>

      {exports.exportMessage && (
        <p className={exports.exportMessage.failed ? 'text-xs text-danger' : 'text-xs text-ok'}>
          {exports.exportMessage.text}
        </p>
      )}

      {status !== 'pending' && (
        <ApprovalFilterCard initial={filters} onApply={resetList} onClear={() => resetList({})} />
      )}

      <ApprovalStatsPanel
        stats={stats}
        statsDays={statsDays}
        statsGroup={statsGroup}
        statsGroupView={statsGroupView}
        statsExporting={exports.statsExporting}
        statsExportMessage={exports.statsExportMessage}
        lastUpdatedAt={lastUpdatedAt}
        refreshing={refreshing}
        autoRefreshEnabled={autoRefreshEnabled}
        autoRefreshError={autoRefreshError}
        refreshIntervalSec={refreshIntervalSec}
        onChangeDays={changeStatsDays}
        onChangeGroup={changeStatsGroup}
        onToggleAutoRefresh={setAutoRefresh}
        onChangeRefreshInterval={setRefreshInterval}
        onExport={() => void exports.exportStatsCsv()}
        onRefresh={() => void refreshStats()}
      />

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{error}</CardContent>
        </Card>
      )}
      {notice && (
        <Card className="border-ok/30 bg-ok/5">
          <CardContent className="p-3 text-xs text-ok">{notice}</CardContent>
        </Card>
      )}

      <ApprovalTableCard
        items={items}
        status={status}
        total={total}
        loading={loading}
        loadingMore={loadingMore}
        cursor={cursor}
        hasActiveFilters={hasActiveFilters}
        onLoadMore={() => void loadMore()}
        onResolve={openResolve}
      />

      <p className="text-[11px] text-muted-foreground">
        只有 <code>ONCALL_APPROVER_ROLES</code> 中的角色能决议，且不能审批自己发起的操作；
        <code>scope=session</code> 授权按「用户 + 会话 + 工具」隔离，默认 8 小时过期。
        运行详情目前只对发起人开放，审批人凭参数快照决议；跨用户读 run 需要单独授权。
      </p>

      <ApprovalResolveDialog
        resolver={resolver}
        setResolver={setResolver}
        onSubmit={() => void submit()}
      />
    </div>
  );
}
