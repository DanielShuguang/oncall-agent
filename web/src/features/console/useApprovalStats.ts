import { useCallback, useEffect, useRef, useState } from 'react';
import { getApprovalStats, type ApprovalStats } from '@/api/approvals';
import type { StatsGroup } from './approvalTypes';
import { APPROVAL_STATS_REFRESH_MS, shouldAutoRefresh } from './approvalStatsRefresh';

export function useApprovalStats(statsDays: number, statsGroup: StatsGroup) {
  const [stats, setStats] = useState<ApprovalStats | null>(null);
  const [statsGroupView, setStatsGroupView] = useState<StatsGroup>(statsGroup);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const statsRequest = useRef(0);
  // 手动刷新单独用令牌管理按钮状态：后台刷新不应把手动刷新卡在「刷新中」。
  const manualRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    void getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup)
      .then((data) => {
        if (!cancelled && statsRequest.current === requestId) {
          setStats(data);
          setStatsGroupView(statsGroup);
          setLastUpdatedAt(Date.now());
        }
        return data;
      })
      .catch(() => {
        if (!cancelled && statsRequest.current === requestId) {
          setStats(null);
          setLastUpdatedAt(null);
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
        }
      } catch {
        // 后台刷新失败时保留上一份统计；手动刷新才回到错误空态。
        if (statsRequest.current === requestId && !silent) {
          setStats(null);
          setLastUpdatedAt(null);
        }
      } finally {
        if (!silent && manualRequest.current === manualId) setRefreshing(false);
      }
    },
    [statsDays, statsGroup],
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (shouldAutoRefresh(document.visibilityState)) void refresh(true);
    }, APPROVAL_STATS_REFRESH_MS);
    const onVisibilityChange = () => {
      if (shouldAutoRefresh(document.visibilityState)) void refresh(true);
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refresh]);

  return { stats, statsGroupView, lastUpdatedAt, refreshing, refresh };
}
