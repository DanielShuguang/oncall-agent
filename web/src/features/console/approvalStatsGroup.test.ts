import { describe, expect, it } from 'vitest';

import {
  APPROVAL_STATS_GROUP_STORAGE_KEY,
  clearApprovalStatsGroup,
  readApprovalStatsGroup,
  writeApprovalStatsGroup,
} from './approvalStatsGroup';

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

describe('approval stats group memory', () => {
  it('默认不分组，只接受 none/tool/approver', () => {
    expect(readApprovalStatsGroup(makeStorage())).toBe('none');
    expect(
      readApprovalStatsGroup(makeStorage({ [APPROVAL_STATS_GROUP_STORAGE_KEY]: 'tool' })),
    ).toBe('tool');
    expect(
      readApprovalStatsGroup(makeStorage({ [APPROVAL_STATS_GROUP_STORAGE_KEY]: 'approver' })),
    ).toBe('approver');
    expect(readApprovalStatsGroup(makeStorage({ [APPROVAL_STATS_GROUP_STORAGE_KEY]: 'bad' }))).toBe(
      'none',
    );
  });

  it('写非默认分组、none 删除、清除删除', () => {
    const storage = makeStorage();
    writeApprovalStatsGroup('tool', storage);
    expect(storage.getItem(APPROVAL_STATS_GROUP_STORAGE_KEY)).toBe('tool');
    writeApprovalStatsGroup('none', storage);
    expect(storage.getItem(APPROVAL_STATS_GROUP_STORAGE_KEY)).toBeNull();
    writeApprovalStatsGroup('bad', storage);
    expect(storage.getItem(APPROVAL_STATS_GROUP_STORAGE_KEY)).toBeNull();
    writeApprovalStatsGroup('approver', storage);
    clearApprovalStatsGroup(storage);
    expect(storage.getItem(APPROVAL_STATS_GROUP_STORAGE_KEY)).toBeNull();
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
    expect(readApprovalStatsGroup(broken)).toBe('none');
    expect(() => writeApprovalStatsGroup('tool', broken)).not.toThrow();
    expect(() => clearApprovalStatsGroup(broken)).not.toThrow();
  });
});
