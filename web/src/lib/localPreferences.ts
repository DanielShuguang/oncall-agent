import {
  EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY,
  PIN_AUDIT_DATE_PRESET_STORAGE_KEY,
  clearAuditDatePresetFor,
  clearLastAuditDatePreset,
} from '@/features/console/auditDatePresets';
import { clearApprovalStatsAutoRefresh } from '@/features/console/approvalStatsRefresh';
import { clearAuditFilterMemory } from '@/features/console/auditFilterMemory';
import {
  clearExportAuditFilterMemory,
  clearPinAuditFilterMemory,
} from '@/features/console/auditPageFilterMemory';
import { clearLastSession } from '@/features/chat/lastSession';

export type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** 切换登录账号时清掉只属于上一位用户的本地界面偏好。 */
export function clearLocalPreferences(storage: PreferenceStorage | null = defaultStorage()): void {
  if (!storage) return;
  clearLastSession(storage);
  clearAuditFilterMemory(storage);
  clearLastAuditDatePreset(storage);
  clearAuditDatePresetFor(PIN_AUDIT_DATE_PRESET_STORAGE_KEY, storage);
  clearAuditDatePresetFor(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY, storage);
  clearPinAuditFilterMemory(storage);
  clearExportAuditFilterMemory(storage);
  clearApprovalStatsAutoRefresh(storage);
}

function defaultStorage(): PreferenceStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
