import { describe, expect, it } from 'vitest';

import {
  AUDIT_DATE_PRESET_STORAGE_KEY,
  auditDatePresetRange,
  clearLastAuditDatePreset,
  readLastAuditDatePreset,
  writeLastAuditDatePreset,
} from './auditDatePresets';

const NOW = new Date('2026-03-15T12:00:00Z');

describe('auditDatePresetRange', () => {
  it('covers the last 7 days including today', () => {
    expect(auditDatePresetRange('last7', NOW)).toEqual({
      from: '2026-03-09',
      to: '2026-03-15',
    });
    expect(auditDatePresetRange('last7', new Date('2026-03-03T12:00:00Z'))).toEqual({
      from: '2026-02-25',
      to: '2026-03-03',
    });
  });

  it('covers the last 30 and 90 days', () => {
    expect(auditDatePresetRange('last30', NOW)).toEqual({
      from: '2026-02-14',
      to: '2026-03-15',
    });
    expect(auditDatePresetRange('last90', NOW)).toEqual({
      from: '2025-12-16',
      to: '2026-03-15',
    });
  });

  it('covers the current UTC month to today', () => {
    expect(auditDatePresetRange('thisMonth', NOW)).toEqual({
      from: '2026-03-01',
      to: '2026-03-15',
    });
  });

  it('covers the full previous UTC month', () => {
    expect(auditDatePresetRange('lastMonth', NOW)).toEqual({
      from: '2026-02-01',
      to: '2026-02-28',
    });
    expect(auditDatePresetRange('lastMonth', new Date('2024-03-15T12:00:00Z'))).toEqual({
      from: '2024-02-01',
      to: '2024-02-29',
    });
    expect(auditDatePresetRange('lastMonth', new Date('2026-01-15T12:00:00Z'))).toEqual({
      from: '2025-12-01',
      to: '2025-12-31',
    });
    expect(auditDatePresetRange('lastMonth', new Date('2026-03-31T12:00:00Z'))).toEqual({
      from: '2026-02-01',
      to: '2026-02-28',
    });
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

describe('auditDatePreset storage', () => {
  it('reads only known preset ids', () => {
    const storage = new MemoryStorage();
    expect(readLastAuditDatePreset(storage)).toBeNull();
    storage.setItem(AUDIT_DATE_PRESET_STORAGE_KEY, 'last30');
    expect(readLastAuditDatePreset(storage)).toBe('last30');
    storage.setItem(AUDIT_DATE_PRESET_STORAGE_KEY, 'custom');
    expect(readLastAuditDatePreset(storage)).toBeNull();
  });

  it('writes and clears the preset without throwing on unavailable storage', () => {
    const storage = new MemoryStorage();
    writeLastAuditDatePreset('lastMonth', storage);
    expect(storage.getItem(AUDIT_DATE_PRESET_STORAGE_KEY)).toBe('lastMonth');
    clearLastAuditDatePreset(storage);
    expect(readLastAuditDatePreset(storage)).toBeNull();

    const throwing = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    };
    expect(() => readLastAuditDatePreset(throwing)).not.toThrow();
    expect(() => writeLastAuditDatePreset('last7', throwing)).not.toThrow();
    expect(() => clearLastAuditDatePreset(throwing)).not.toThrow();
    expect(readLastAuditDatePreset(throwing)).toBeNull();
  });
});
