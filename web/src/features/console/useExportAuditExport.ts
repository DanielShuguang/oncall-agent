import { useRef, useState } from 'react';
import { downloadBlob } from '@/lib/download';
import { exportExportAuditsCsv, type ExportAuditFilters } from '@/api/exportAudits';

export interface ExportAuditExportState {
  exporting: boolean;
  message: string | null;
  exportCsv: () => Promise<void>;
  /** 筛选已变化：丢弃在途导出结果，清掉旧提示。 */
  invalidate: () => void;
}

/** 导出审计 CSV；导出本身会新增一条审计记录，成功后刷新列表（ADR-0096）。 */
export function useExportAuditExport(
  filters: ExportAuditFilters,
  onExported: () => void,
): ExportAuditExportState {
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const exportRequest = useRef(0);

  const invalidate = () => {
    exportRequest.current += 1;
    setExporting(false);
    setMessage(null);
  };

  const exportCsv = async () => {
    const request = exportRequest.current;
    setExporting(true);
    setMessage(null);
    try {
      const result = await exportExportAuditsCsv(filters);
      if (request !== exportRequest.current) return;
      downloadBlob(result.blob, 'export-audits.csv');
      setMessage(`已导出 ${result.count} 条${result.truncated ? '（已截断）' : ''}`);
      onExported();
    } catch (caught) {
      if (request !== exportRequest.current) return;
      setMessage(caught instanceof Error ? caught.message : '导出失败');
    } finally {
      if (request === exportRequest.current) setExporting(false);
    }
  };

  return { exporting, message, exportCsv, invalidate };
}
