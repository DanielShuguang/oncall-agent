import { clearLastAuditDatePreset } from '@/features/console/auditDatePresets';
import { clearAuditFilterMemory } from '@/features/console/auditFilterMemory';
import { clearLastSession } from '@/features/chat/lastSession';

export type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** 切换登录账号时清掉只属于上一位用户的本地界面偏好。 */
export function clearLocalPreferences(storage: PreferenceStorage | null = defaultStorage()): void {
  if (!storage) return;
  clearLastSession(storage);
  clearAuditFilterMemory(storage);
  clearLastAuditDatePreset(storage);
}

function defaultStorage(): PreferenceStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
