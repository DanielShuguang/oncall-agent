/** 审计日期范围快捷预设（ADR-0071）；记住上次选择（ADR-0075）。 */

export type AuditDatePreset = 'last7' | 'last30' | 'last90' | 'thisMonth' | 'lastMonth';

export const AUDIT_DATE_PRESET_STORAGE_KEY = 'oncall.audit-date-preset.v1';

type PresetStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

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

/** 当前手填/预设区间匹配的预设；用于高亮，不写回存储。 */
export function activeAuditDatePreset(
  from: string,
  to: string,
  now: Date = new Date(),
): AuditDatePreset | null {
  return (
    AUDIT_DATE_PRESETS.find(({ value }) => {
      const range = auditDatePresetRange(value, now);
      return range.from === from && range.to === to;
    })?.value ?? null
  );
}
function defaultPresetStorage(): PresetStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    // 隐私模式/禁用存储时按「没有记住」处理，不影响筛选本身。
    return null;
  }
}

function isAuditDatePreset(value: string | null): value is AuditDatePreset {
  return AUDIT_DATE_PRESETS.some((preset) => preset.value === value);
}

/** 只持久化预设 ID；手填日期不保存，避免下次打开落到过期窗口。 */
export function readLastAuditDatePreset(
  storage: PresetStorage | null = defaultPresetStorage(),
): AuditDatePreset | null {
  if (!storage) return null;
  try {
    const value = storage.getItem(AUDIT_DATE_PRESET_STORAGE_KEY);
    return isAuditDatePreset(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeLastAuditDatePreset(
  preset: AuditDatePreset,
  storage: PresetStorage | null = defaultPresetStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(AUDIT_DATE_PRESET_STORAGE_KEY, preset);
  } catch {
    // 存储不可用时静默降级；当前这次筛选仍然生效。
  }
}

export function clearLastAuditDatePreset(
  storage: PresetStorage | null = defaultPresetStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(AUDIT_DATE_PRESET_STORAGE_KEY);
  } catch {
    // 同 write：清理失败不影响页面状态。
  }
}

export const PIN_AUDIT_DATE_PRESET_STORAGE_KEY = 'oncall.pin-audit-date-preset.v1';
export const EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY = 'oncall.export-audit-date-preset.v1';

/** 通用预设记忆：不同审计页用独立 key，避免跨页互相覆盖。 */
export function readAuditDatePresetFor(
  key: string,
  storage: PresetStorage | null = defaultPresetStorage(),
): AuditDatePreset | null {
  if (!storage) return null;
  try {
    const value = storage.getItem(key);
    return isAuditDatePreset(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeAuditDatePresetFor(
  key: string,
  preset: AuditDatePreset,
  storage: PresetStorage | null = defaultPresetStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(key, preset);
  } catch {
    // 存储不可用时静默降级；当前这次筛选仍然生效。
  }
}

export function clearAuditDatePresetFor(
  key: string,
  storage: PresetStorage | null = defaultPresetStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // 清理失败不影响页面状态。
  }
}
