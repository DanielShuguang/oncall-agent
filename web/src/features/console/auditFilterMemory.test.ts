import { describe, expect, it } from 'vitest';

import {
  AUDIT_FILTER_MEMORY_KEY,
  clearAuditFilterMemory,
  readAuditFilterMemory,
  writeAuditFilterMemory,
  type AuditFilterMemory,
} from './auditFilterMemory';

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

const memory: AuditFilterMemory = {
  userId: 'u_102',
  sessionId: 'sess_a',
  statsDays: 7,
};

describe('auditFilterMemory', () => {
  it('reads trimmed filters and a valid stats window', () => {
    const storage = new MemoryStorage();
    storage.setItem(
      AUDIT_FILTER_MEMORY_KEY,
      JSON.stringify({ userId: ' u_102 ', sessionId: 'sess_a ', statsDays: 7 }),
    );

    expect(readAuditFilterMemory(storage)).toEqual({
      userId: 'u_102',
      sessionId: 'sess_a',
      statsDays: 7,
    });
  });

  it('ignores invalid ids and falls back to 30 days for an unknown window', () => {
    const storage = new MemoryStorage();
    storage.setItem(AUDIT_FILTER_MEMORY_KEY, JSON.stringify({ userId: 7, statsDays: 7 }));
    expect(readAuditFilterMemory(storage)).toBeNull();

    storage.setItem(AUDIT_FILTER_MEMORY_KEY, JSON.stringify({ userId: 'u_102', statsDays: 14 }));
    expect(readAuditFilterMemory(storage)).toEqual({
      userId: 'u_102',
      sessionId: '',
      statsDays: 30,
    });
  });

  it('treats empty filters at the default window as no memory', () => {
    const storage = new MemoryStorage();
    storage.setItem(
      AUDIT_FILTER_MEMORY_KEY,
      JSON.stringify({ userId: '', sessionId: '', statsDays: 30 }),
    );
    expect(readAuditFilterMemory(storage)).toBeNull();
  });

  it('writes, normalizes and removes the remembered state', () => {
    const storage = new MemoryStorage();
    writeAuditFilterMemory({ ...memory, userId: ' u_102 ' }, storage);
    expect(readAuditFilterMemory(storage)).toEqual(memory);

    writeAuditFilterMemory({ userId: '', sessionId: '', statsDays: 30 }, storage);
    expect(readAuditFilterMemory(storage)).toBeNull();

    writeAuditFilterMemory(memory, storage);
    clearAuditFilterMemory(storage);
    expect(readAuditFilterMemory(storage)).toBeNull();
  });

  it('does not throw when storage is unavailable', () => {
    const storage = {
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

    expect(readAuditFilterMemory(storage)).toBeNull();
    expect(() => writeAuditFilterMemory(memory, storage)).not.toThrow();
    expect(() => clearAuditFilterMemory(storage)).not.toThrow();
  });
});
