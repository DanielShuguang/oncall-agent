import { describe, expect, it } from 'vitest';
import {
  EXPORT_AUDIT_FILTER_STORAGE_KEY,
  PIN_AUDIT_FILTER_STORAGE_KEY,
  clearExportAuditFilterMemory,
  clearPinAuditFilterMemory,
  readExportAuditFilterMemory,
  readPinAuditFilterMemory,
  writeExportAuditFilterMemory,
  writePinAuditFilterMemory,
} from './auditPageFilterMemory';

describe('auditPageFilterMemory', () => {
  it('置顶与导出过滤各自独立保存', () => {
    const storage = new MemoryStorage();
    writePinAuditFilterMemory({ userId: ' u_1 ', sessionId: 's_1', action: 'pin' }, storage);
    writeExportAuditFilterMemory({ userId: 'u_2', resource: 'approvals' }, storage);

    expect(readPinAuditFilterMemory(storage)).toEqual({
      userId: 'u_1',
      sessionId: 's_1',
      action: 'pin',
    });
    expect(readExportAuditFilterMemory(storage)).toEqual({
      userId: 'u_2',
      resource: 'approvals',
    });
    expect(storage.getItem(PIN_AUDIT_FILTER_STORAGE_KEY)).not.toBeNull();
    expect(storage.getItem(EXPORT_AUDIT_FILTER_STORAGE_KEY)).not.toBeNull();
  });

  it('忽略非法枚举与超长 id，不把脏值带进筛选', () => {
    const storage = new MemoryStorage();
    storage.setItem(
      PIN_AUDIT_FILTER_STORAGE_KEY,
      JSON.stringify({ userId: 'x'.repeat(65), sessionId: 's_1', action: 'delete' }),
    );
    storage.setItem(
      EXPORT_AUDIT_FILTER_STORAGE_KEY,
      JSON.stringify({ userId: 'u_1', resource: 'secrets' }),
    );

    expect(readPinAuditFilterMemory(storage)).toEqual({
      userId: '',
      sessionId: 's_1',
      action: 'all',
    });
    expect(readExportAuditFilterMemory(storage)).toEqual({ userId: 'u_1', resource: '' });
  });

  it('空过滤会删除 key，清除只影响本页', () => {
    const storage = new MemoryStorage();
    writePinAuditFilterMemory({ userId: 'u_1', sessionId: '', action: 'all' }, storage);
    writeExportAuditFilterMemory({ userId: 'u_2', resource: 'approvals' }, storage);

    writePinAuditFilterMemory({ userId: '', sessionId: '', action: 'all' }, storage);
    expect(storage.getItem(PIN_AUDIT_FILTER_STORAGE_KEY)).toBeNull();
    expect(readExportAuditFilterMemory(storage)).toEqual({
      userId: 'u_2',
      resource: 'approvals',
    });

    clearExportAuditFilterMemory(storage);
    expect(storage.getItem(EXPORT_AUDIT_FILTER_STORAGE_KEY)).toBeNull();
  });

  it('损坏 JSON 与不可用存储都静默回退', () => {
    const storage = new MemoryStorage();
    storage.setItem(PIN_AUDIT_FILTER_STORAGE_KEY, '{not-json');
    storage.setItem(EXPORT_AUDIT_FILTER_STORAGE_KEY, '[]');

    expect(readPinAuditFilterMemory(storage)).toBeNull();
    expect(readExportAuditFilterMemory(storage)).toBeNull();
    expect(() => {
      writePinAuditFilterMemory({ userId: 'u_1', sessionId: '', action: 'all' }, null);
      clearPinAuditFilterMemory(null);
      writeExportAuditFilterMemory({ userId: 'u_1', resource: '' }, null);
      clearExportAuditFilterMemory(null);
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
