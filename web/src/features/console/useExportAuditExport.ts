import { useState } from 'react';
import { downloadBlob } from '@/lib/download';
import { exportExportAuditsCsv, type ExportAuditFilters } from '@/api/exportAudits';

export interface ExportAuditExportState {
  exporting: boolean;
  message: string | null;
  exportCsv: () => Promise<void>;
}

/** 导出审计 CSV；导出本身会新增一条审计记录，成功后刷新列表（ADR-0096）。 */
export function useExportAuditExport(
  filters: ExportAuditFilters,
  onExported: () => void,
): ExportAuditExportState {
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const exportCsv = async () => {
    setExporting(true);
    setMessage(null);
    try {
      const result = await exportExportAuditsCsv(filters);
      downloadBlob(result.blob, 'export-audits.csv');
      setMessage(`已导出 ${result.count} 条${result.truncated ? '（已截断）' : ''}`);
      onExported();
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  return { exporting, message, exportCsv };
}
