import { useEffect, useRef, useState } from 'react';
import { getApprovalStats, type ApprovalStats } from '@/api/approvals';
import type { StatsGroup } from './approvalTypes';

export function useApprovalStats(statsDays: number, statsGroup: StatsGroup) {
  const [stats, setStats] = useState<ApprovalStats | null>(null);
  const [statsGroupView, setStatsGroupView] = useState<StatsGroup>(statsGroup);
  const statsRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    void getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup)
      .then((data) => {
        if (!cancelled && statsRequest.current === requestId) {
          setStats(data);
          setStatsGroupView(statsGroup);
        }
        return data;
      })
      .catch(() => {
        if (!cancelled && statsRequest.current === requestId) setStats(null);
      });
    return () => {
      cancelled = true;
      statsRequest.current += 1;
    };
  }, [statsDays, statsGroup]);

  const refresh = async () => {
    const requestId = ++statsRequest.current;
    try {
      const data = await getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup);
      if (statsRequest.current === requestId) {
        setStats(data);
        setStatsGroupView(statsGroup);
      }
    } catch {
      if (statsRequest.current === requestId) setStats(null);
    }
  };

  return { stats, statsGroupView, refresh };
}
