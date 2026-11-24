import { describe, expect, it } from 'vitest';
import {
  AUDIT_DATE_PRESET_STORAGE_KEY,
  EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY,
  PIN_AUDIT_DATE_PRESET_STORAGE_KEY,
} from '@/features/console/auditDatePresets';
import { AUDIT_FILTER_MEMORY_KEY } from '@/features/console/auditFilterMemory';
import {
  EXPORT_AUDIT_FILTER_STORAGE_KEY,
  PIN_AUDIT_FILTER_STORAGE_KEY,
} from '@/features/console/auditPageFilterMemory';
import { PIN_AUDIT_STATS_WINDOW_STORAGE_KEY } from '@/features/console/pinAuditStatsWindow';
import {
  APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY,
  APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY,
} from '@/features/console/approvalStatsRefresh';
import { LAST_SESSION_KEY } from '@/features/chat/lastSession';
import { clearLocalPreferences } from './localPreferences';

describe('clearLocalPreferences', () => {
  it('只清掉会话/审计相关的本地偏好', () => {
    const storage = new MemoryStorage();
    storage.setItem(LAST_SESSION_KEY, 'sess_1');
    storage.setItem(AUDIT_FILTER_MEMORY_KEY, '{"userId":"u_1","statsDays":7}');
    storage.setItem(AUDIT_DATE_PRESET_STORAGE_KEY, 'last7');
    storage.setItem(PIN_AUDIT_DATE_PRESET_STORAGE_KEY, 'last30');
    storage.setItem(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY, 'lastMonth');
    storage.setItem(PIN_AUDIT_FILTER_STORAGE_KEY, '{"userId":"u_1"}');
    storage.setItem(EXPORT_AUDIT_FILTER_STORAGE_KEY, '{"userId":"u_2"}');
    storage.setItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY, '90');
    storage.setItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY, 'off');
    storage.setItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY, '60');
    storage.setItem('oncall.token', 'keep-token');
    storage.setItem('unrelated', 'keep');

    clearLocalPreferences(storage);

    expect(storage.getItem(LAST_SESSION_KEY)).toBeNull();
    expect(storage.getItem(AUDIT_FILTER_MEMORY_KEY)).toBeNull();
    expect(storage.getItem(AUDIT_DATE_PRESET_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(PIN_AUDIT_DATE_PRESET_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(EXPORT_AUDIT_DATE_PRESET_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(PIN_AUDIT_FILTER_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(EXPORT_AUDIT_FILTER_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY)).toBeNull();
    expect(storage.getItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY)).toBeNull();
    expect(storage.getItem('oncall.token')).toBe('keep-token');
    expect(storage.getItem('unrelated')).toBe('keep');
  });

  it('没有可用存储时静默跳过', () => {
    expect(() => {
      clearLocalPreferences(null);
    }).not.toThrow();
  });
});

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}
