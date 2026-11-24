import { describe, expect, it } from 'vitest';

import {
  PIN_AUDIT_STATS_WINDOW_STORAGE_KEY,
  clearPinAuditStatsWindow,
  readPinAuditStatsWindow,
  writePinAuditStatsWindow,
} from './pinAuditStatsWindow';

function makeStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
    clear: () => data.clear(),
    key: (index) => Array.from(data.keys())[index] ?? null,
    get length() {
      return data.size;
    },
  } as Storage;
}

describe('pin audit stats window memory', () => {
  it('默认 30 天，只接受 7/30/90', () => {
    expect(readPinAuditStatsWindow(makeStorage())).toBe(30);
    expect(
      readPinAuditStatsWindow(makeStorage({ [PIN_AUDIT_STATS_WINDOW_STORAGE_KEY]: '7' })),
    ).toBe(7);
    expect(
      readPinAuditStatsWindow(makeStorage({ [PIN_AUDIT_STATS_WINDOW_STORAGE_KEY]: '45' })),
    ).toBe(30);
    expect(
      readPinAuditStatsWindow(makeStorage({ [PIN_AUDIT_STATS_WINDOW_STORAGE_KEY]: 'bad' })),
    ).toBe(30);
  });

  it('写非默认窗口、30 天删除、清除删除', () => {
    const storage = makeStorage();
    writePinAuditStatsWindow(90, storage);
    expect(storage.getItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY)).toBe('90');
    writePinAuditStatsWindow(30, storage);
    expect(storage.getItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY)).toBeNull();
    writePinAuditStatsWindow(7, storage);
    clearPinAuditStatsWindow(storage);
    expect(storage.getItem(PIN_AUDIT_STATS_WINDOW_STORAGE_KEY)).toBeNull();
  });

  it('存储不可用时静默回退', () => {
    const broken = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
      removeItem: () => {
        throw new Error('denied');
      },
    } as unknown as Storage;
    expect(readPinAuditStatsWindow(broken)).toBe(30);
    expect(() => writePinAuditStatsWindow(7, broken)).not.toThrow();
    expect(() => clearPinAuditStatsWindow(broken)).not.toThrow();
  });
});
