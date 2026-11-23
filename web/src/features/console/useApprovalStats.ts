import { useCallback, useEffect, useRef, useState } from 'react';
import { getApprovalStats, type ApprovalStats } from '@/api/approvals';
import type { StatsGroup } from './approvalTypes';
import { APPROVAL_STATS_REFRESH_MS, shouldAutoRefresh } from './approvalStatsRefresh';

export function useApprovalStats(statsDays: number, statsGroup: StatsGroup) {
  const [stats, setStats] = useState<ApprovalStats | null>(null);
  const [statsGroupView, setStatsGroupView] = useState<StatsGroup>(statsGroup);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [autoRefreshError, setAutoRefreshError] = useState<string | null>(null);
  const statsRequest = useRef(0);
  // 手动刷新单独用令牌管理按钮状态：后台刷新不应把手动刷新卡在「刷新中」。
  const manualRequest = useRef(0);
  // 关闭开关时，暂停前发出的静默请求仍可能失败；用 ref 判断「当前是否仍启用」，
  // 避免暂停后又冒出一条自动刷新失败提示。
  const autoRefreshEnabledRef = useRef(true);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    void getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup)
      .then((data) => {
        if (!cancelled && statsRequest.current === requestId) {
          setStats(data);
          setStatsGroupView(statsGroup);
          setLastUpdatedAt(Date.now());
          setAutoRefreshError(null);
        }
        return data;
      })
      .catch(() => {
        if (!cancelled && statsRequest.current === requestId) {
          setStats(null);
          setLastUpdatedAt(null);
          setAutoRefreshError(null);
        }
      });
    return () => {
      cancelled = true;
      statsRequest.current += 1;
    };
  }, [statsDays, statsGroup]);

  const refresh = useCallback(
    async (silent = false) => {
      const requestId = ++statsRequest.current;
      const manualId = silent ? 0 : ++manualRequest.current;
      if (!silent) setRefreshing(true);
      try {
        const data = await getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup);
        if (statsRequest.current === requestId) {
          setStats(data);
          setStatsGroupView(statsGroup);
          setLastUpdatedAt(Date.now());
          setAutoRefreshError(null);
        }
      } catch {
        // 后台刷新失败时保留上一份统计；手动刷新才回到错误空态。
        if (statsRequest.current === requestId && !silent) {
          setStats(null);
          setLastUpdatedAt(null);
          setAutoRefreshError(null);
        } else if (statsRequest.current === requestId && autoRefreshEnabledRef.current) {
          setAutoRefreshError('自动刷新失败，稍后重试');
        }
      } finally {
        if (!silent && manualRequest.current === manualId) setRefreshing(false);
      }
    },
    [statsDays, statsGroup],
  );

  const setAutoRefresh = useCallback(
    (enabled: boolean) => {
      autoRefreshEnabledRef.current = enabled;
      setAutoRefreshEnabled(enabled);
      setAutoRefreshError(null);
      // 重新打开时立即补拉一次，不必等下一个 30 秒。
      if (enabled) void refresh(true);
    },
    [refresh],
  );

  useEffect(() => {
    if (!autoRefreshEnabled) return;
    const timer = window.setInterval(() => {
      if (shouldAutoRefresh(document.visibilityState, autoRefreshEnabled)) void refresh(true);
    }, APPROVAL_STATS_REFRESH_MS);
    const onVisibilityChange = () => {
      if (shouldAutoRefresh(document.visibilityState, autoRefreshEnabled)) void refresh(true);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [autoRefreshEnabled, refresh]);

  return {
    stats,
    statsGroupView,
    lastUpdatedAt,
    refreshing,
    autoRefreshEnabled,
    autoRefreshError,
    setAutoRefresh,
    refresh,
  };
}
