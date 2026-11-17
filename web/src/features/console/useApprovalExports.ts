import { useRef, useState } from 'react';
import {
  exportApprovalStatsCsv,
  exportApprovalsCsv,
  type ApprovalListFilters,
} from '@/api/approvals';
import { downloadBlob } from '@/lib/download';
import type { StatsGroup } from './approvalTypes';

export function useApprovalExports(
  status: string,
  filters: ApprovalListFilters,
  statsDays: number,
  statsGroup: StatsGroup,
) {
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<{ text: string; failed: boolean } | null>(
    null,
  );
  const [statsExporting, setStatsExporting] = useState(false);
  const [statsExportMessage, setStatsExportMessage] = useState<{
    text: string;
    failed: boolean;
  } | null>(null);
  const exportRequest = useRef(0);
  const statsExportRequest = useRef(0);

  const invalidateList = () => {
    exportRequest.current += 1;
    setExporting(false);
    setExportMessage(null);
  };

  const invalidateStats = () => {
    statsExportRequest.current += 1;
    setStatsExporting(false);
    setStatsExportMessage(null);
  };

  const exportCsv = async () => {
    if (exporting) return;
    const requestId = ++exportRequest.current;
    setExporting(true);
    setExportMessage(null);
    try {
      const result = await exportApprovalsCsv(status, filters);
      if (exportRequest.current !== requestId) return;
      downloadBlob(result.blob, `approvals-${status}.csv`);
      setExportMessage({
        failed: false,
        text: result.truncated
          ? `已导出前 ${result.count} 条；超过 5000 条上限，已截断。`
          : `已导出 ${result.count} 条审批。`,
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

  const exportStatsCsv = async () => {
    if (statsExporting) return;
    const requestId = ++statsExportRequest.current;
    setStatsExporting(true);
    setStatsExportMessage(null);
    try {
      const result = await exportApprovalStatsCsv(
        statsDays,
        statsGroup === 'none' ? null : statsGroup,
      );
      if (statsExportRequest.current !== requestId) return;
      const groupLabel =
        result.groupBy === null ? '不分组' : result.groupBy === 'tool' ? '按工具' : '按审批人';
      downloadBlob(result.blob, `approval-stats-${result.days}d-${result.groupBy ?? 'none'}.csv`);
      setStatsExportMessage({
        failed: false,
        text: result.groupsTruncated
          ? `已导出近 ${result.days} 天统计（${groupLabel}）；分组超过 20 组，仅含前 20 组。`
          : `已导出近 ${result.days} 天统计（${groupLabel}）。`,
      });
    } catch (exc) {
      if (statsExportRequest.current !== requestId) return;
      setStatsExportMessage({
        failed: true,
        text: exc instanceof Error ? exc.message : '导出统计失败',
      });
    } finally {
      if (statsExportRequest.current === requestId) setStatsExporting(false);
    }
  };

  return {
    exporting,
    exportMessage,
    statsExporting,
    statsExportMessage,
    exportCsv,
    exportStatsCsv,
    invalidateList,
    invalidateStats,
  };
}
