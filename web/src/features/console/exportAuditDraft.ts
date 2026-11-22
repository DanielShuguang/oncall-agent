import type { ExportAuditFilters, ExportResource } from '@/api/exportAudits';

export interface ExportAuditDraft {
  userId: string;
  resource: '' | ExportResource;
  createdFrom: string;
  createdTo: string;
}

export const EMPTY_EXPORT_AUDIT_DRAFT: ExportAuditDraft = {
  userId: '',
  resource: '',
  createdFrom: '',
  createdTo: '',
};

/** 把草稿变成请求过滤；空白值不发送，日期为空时两端都不发送。 */
export function toExportAuditFilters(draft: ExportAuditDraft): ExportAuditFilters {
  return {
    userId: draft.userId.trim() || undefined,
    resource: draft.resource || undefined,
    createdFrom: draft.createdFrom || undefined,
    createdTo: draft.createdTo || undefined,
  };
}
