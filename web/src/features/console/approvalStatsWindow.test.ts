import { describe, expect, it } from 'vitest';

import {
  APPROVAL_STATS_WINDOW_STORAGE_KEY,
  clearApprovalStatsWindow,
  readApprovalStatsWindow,
  writeApprovalStatsWindow,
} from './approvalStatsWindow';

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

describe('approval stats window memory', () => {
  it('默认 7 天，只接受 7/30/90', () => {
    expect(readApprovalStatsWindow(makeStorage())).toBe(7);
    expect(
      readApprovalStatsWindow(makeStorage({ [APPROVAL_STATS_WINDOW_STORAGE_KEY]: '30' })),
    ).toBe(30);
    expect(
      readApprovalStatsWindow(makeStorage({ [APPROVAL_STATS_WINDOW_STORAGE_KEY]: '45' })),
    ).toBe(7);
    expect(
      readApprovalStatsWindow(makeStorage({ [APPROVAL_STATS_WINDOW_STORAGE_KEY]: 'bad' })),
    ).toBe(7);
  });

  it('写非默认窗口、7 天删除、清除删除', () => {
    const storage = makeStorage();
    writeApprovalStatsWindow(90, storage);
    expect(storage.getItem(APPROVAL_STATS_WINDOW_STORAGE_KEY)).toBe('90');
    writeApprovalStatsWindow(7, storage);
    expect(storage.getItem(APPROVAL_STATS_WINDOW_STORAGE_KEY)).toBeNull();
    writeApprovalStatsWindow(30, storage);
    clearApprovalStatsWindow(storage);
    expect(storage.getItem(APPROVAL_STATS_WINDOW_STORAGE_KEY)).toBeNull();
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
    expect(readApprovalStatsWindow(broken)).toBe(7);
    expect(() => writeApprovalStatsWindow(30, broken)).not.toThrow();
    expect(() => clearApprovalStatsWindow(broken)).not.toThrow();
  });
});
