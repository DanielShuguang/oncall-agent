/** 审计日期范围快捷预设（ADR-0071）。 */

export type AuditDatePreset = 'last7' | 'last30' | 'last90' | 'thisMonth' | 'lastMonth';

export const AUDIT_DATE_PRESETS: { value: AuditDatePreset; label: string }[] = [
  { value: 'last7', label: '近 7 天' },
  { value: 'last30', label: '近 30 天' },
  { value: 'last90', label: '近 90 天' },
  { value: 'thisMonth', label: '本月' },
  { value: 'lastMonth', label: '上月' },
];

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function utcToday(now: Date): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

/** 返回 UTC 自然日闭区间；调用方再交给现有筛选校验。 */
export function auditDatePresetRange(
  preset: AuditDatePreset,
  now: Date = new Date(),
): { from: string; to: string } {
  const today = utcToday(now);
  if (preset === 'thisMonth') {
    const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
    return { from: isoDate(first), to: isoDate(today) };
  }
  if (preset === 'lastMonth') {
    const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 1, 1));
    const last = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 0));
    return { from: isoDate(first), to: isoDate(last) };
  }
  const days = preset === 'last7' ? 7 : preset === 'last30' ? 30 : 90;
  const from = new Date(today);
  from.setUTCDate(from.getUTCDate() - (days - 1));
  return { from: isoDate(from), to: isoDate(today) };
}
