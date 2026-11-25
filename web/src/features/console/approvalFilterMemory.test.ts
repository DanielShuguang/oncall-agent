import { describe, expect, it } from 'vitest';
import {
  APPROVAL_FILTER_STORAGE_KEY,
  clearApprovalFilterMemory,
  readApprovalFilterMemory,
  writeApprovalFilterMemory,
} from './approvalFilterMemory';

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
    values,
  };
}

describe('approvalFilterMemory', () => {
  it('保存并读取已应用的已办筛选', () => {
    const storage = memoryStorage();
    writeApprovalFilterMemory(
      {
        tool: ' create_ticket ',
        resolvedBy: ' admin ',
        resolvedFrom: '2026-01-01',
        resolvedTo: '2026-01-02',
      },
      storage,
    );

    expect(readApprovalFilterMemory(storage)).toEqual({
      tool: 'create_ticket',
      resolvedBy: 'admin',
      resolvedFrom: '2026-01-01',
      resolvedTo: '2026-01-02',
    });
  });

  it('空筛选删除 key，非法字段忽略而不虚构', () => {
    const storage = memoryStorage();
    storage.values.set(
      APPROVAL_FILTER_STORAGE_KEY,
      JSON.stringify({ tool: 'x'.repeat(65), resolvedBy: 1, resolvedFrom: 'bad', resolvedTo: '' }),
    );
    expect(readApprovalFilterMemory(storage)).toEqual({});
    expect(storage.values.has(APPROVAL_FILTER_STORAGE_KEY)).toBe(false);

    writeApprovalFilterMemory({}, storage);
    expect(storage.values.has(APPROVAL_FILTER_STORAGE_KEY)).toBe(false);
  });

  it('损坏 JSON 与不可用存储回退为空', () => {
    const broken = memoryStorage({ [APPROVAL_FILTER_STORAGE_KEY]: '{' });
    expect(readApprovalFilterMemory(broken)).toEqual({});

    const unavailable = {
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
    expect(readApprovalFilterMemory(unavailable)).toEqual({});
    expect(() => writeApprovalFilterMemory({ tool: 'x' }, unavailable)).not.toThrow();
    expect(() => clearApprovalFilterMemory(unavailable)).not.toThrow();
  });

  it('清除后读取为空', () => {
    const storage = memoryStorage();
    writeApprovalFilterMemory({ tool: 'query_cmdb' }, storage);
    clearApprovalFilterMemory(storage);
    expect(readApprovalFilterMemory(storage)).toEqual({});
  });
});
