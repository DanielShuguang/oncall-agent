import { useRef, useState } from 'react';
import { exportSessionPinAuditsCsv, type SessionPinAuditFilters } from '@/api/pinAudits';
import { downloadBlob } from '@/lib/download';

/** 置顶审计列表导出的状态与竞态守卫（ADR-0084/0090）。 */
export function usePinAuditExport() {
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<{ text: string; failed: boolean } | null>(
    null,
  );
  const exportRequest = useRef(0);

  const invalidate = () => {
    exportRequest.current += 1;
    setExporting(false);
    setExportMessage(null);
  };

  const exportCsv = async (filters: SessionPinAuditFilters) => {
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

  return { exporting, exportMessage, exportCsv, invalidate };
}
