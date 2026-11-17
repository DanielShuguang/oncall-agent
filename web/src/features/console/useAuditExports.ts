/** 恢复审计的列表/统计导出状态，独立于页面数据加载。 */

import { useRef, useState } from 'react';
import {
  exportSessionRestoreAuditsCsv,
  exportSessionRestoreAuditStatsCsv,
  type SessionRestoreAuditFilters,
  type SessionRestoreAuditStats,
} from '@/api/sessionAudits';
import { downloadBlob } from '@/lib/download';

export function useAuditExports(
  filters: SessionRestoreAuditFilters,
  statsDays: number,
  hasDateRange: boolean,
  stats: SessionRestoreAuditStats | null,
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

  const invalidate = () => {
    exportRequest.current += 1;
    setExporting(false);
    setExportMessage(null);
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
      const result = await exportSessionRestoreAuditsCsv(filters);
      if (exportRequest.current !== requestId) return;
      downloadBlob(result.blob, 'session-restores.csv');
      setExportMessage({
        failed: false,
        text: result.truncated
          ? `已导出前 ${result.count} 条；超过 5000 条上限，已截断。`
          : `已导出 ${result.count} 条恢复审计。`,
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

  const exportStats = async () => {
    if (statsExporting || !stats) return;
    const requestId = ++statsExportRequest.current;
    setStatsExporting(true);
    setStatsExportMessage(null);
    try {
      const result = await exportSessionRestoreAuditStatsCsv(
        hasDateRange ? null : statsDays,
        filters,
      );
      if (statsExportRequest.current !== requestId) return;
      const rangeLabel = hasDateRange
        ? `${filters.restoredFrom ?? ''} 至 ${filters.restoredTo ?? ''}`
        : `近 ${result.days} 天`;
      const fileWindow = hasDateRange
        ? `${filters.restoredFrom ?? ''}_${filters.restoredTo ?? ''}`
        : `${result.days}d`;
      downloadBlob(result.blob, `session-restore-stats-${fileWindow}.csv`);
      setStatsExportMessage({
        failed: false,
        text: `已导出 ${rangeLabel} 统计：恢复 ${result.restores} 次 / ${result.users} 个用户 / ${result.sessions} 个会话。`,
      });
    } catch (exc) {
      if (statsExportRequest.current !== requestId) return;
      setStatsExportMessage({
        failed: true,
        text: exc instanceof Error ? exc.message : '统计导出失败',
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
    exportStats,
    invalidate,
  };
}
