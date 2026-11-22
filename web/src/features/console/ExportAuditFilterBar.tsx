import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AUDIT_DATE_PRESETS, type AuditDatePreset } from './auditDatePresets';
import { EXPORT_RESOURCE_LABEL, type ExportResource } from '@/api/exportAudits';
import type { ExportAuditDraft } from './exportAuditDraft';

export interface ExportAuditFilterBarProps {
  draft: ExportAuditDraft;
  activePreset: AuditDatePreset | null;
  filterError: string | null;
  exporting: boolean;
  exportMessage: string | null;
  onChange: (draft: ExportAuditDraft) => void;
  onApply: () => void;
  onClear: () => void;
  onPreset: (preset: AuditDatePreset) => void;
  onExport: () => void;
}

/** 导出审计筛选卡；日期预设复用审计页的 UTC 自然日算法（ADR-0071）。 */
export function ExportAuditFilterBar({
  draft,
  activePreset,
  filterError,
  exporting,
  exportMessage,
  onChange,
  onApply,
  onClear,
  onPreset,
  onExport,
}: ExportAuditFilterBarProps) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">快捷日期（UTC）</span>
          {AUDIT_DATE_PRESETS.map((preset) => (
            <Button
              key={preset.value}
              aria-pressed={activePreset === preset.value}
              className="h-7 text-xs"
              size="sm"
              variant={activePreset === preset.value ? 'default' : 'outline'}
              onClick={() => onPreset(preset.value)}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-40 flex-1">
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-user">
              用户
            </label>
            <Input
              id="export-user"
              className="h-8 text-xs"
              placeholder="如 u_102"
              value={draft.userId}
              onChange={(event) => onChange({ ...draft, userId: event.target.value })}
            />
          </div>
          <div className="min-w-40">
            <label
              className="mb-1 block text-[11px] text-muted-foreground"
              htmlFor="export-resource"
            >
              资源
            </label>
            <select
              id="export-resource"
              className="h-8 w-full rounded-md border bg-panel px-2 text-xs"
              value={draft.resource}
              onChange={(event) =>
                onChange({ ...draft, resource: event.target.value as '' | ExportResource })
              }
            >
              <option value="">全部资源</option>
              {(Object.keys(EXPORT_RESOURCE_LABEL) as ExportResource[]).map((resource) => (
                <option key={resource} value={resource}>
                  {EXPORT_RESOURCE_LABEL[resource]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-from">
              起（UTC）
            </label>
            <Input
              id="export-from"
              type="date"
              className="h-8 w-36 text-xs"
              value={draft.createdFrom}
              onChange={(event) => onChange({ ...draft, createdFrom: event.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="export-to">
              止（UTC）
            </label>
            <Input
              id="export-to"
              type="date"
              className="h-8 w-36 text-xs"
              value={draft.createdTo}
              onChange={(event) => onChange({ ...draft, createdTo: event.target.value })}
            />
          </div>
          <Button size="sm" className="h-8 text-xs" onClick={onApply}>
            筛选
          </Button>
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onClear}>
            清除
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            disabled={exporting}
            onClick={onExport}
          >
            {exporting ? '导出中…' : '导出 CSV'}
          </Button>
        </div>
        {filterError && <span className="text-xs text-danger">{filterError}</span>}
        {exportMessage && <p className="text-xs text-muted-foreground">{exportMessage}</p>}
      </CardContent>
    </Card>
  );
}
