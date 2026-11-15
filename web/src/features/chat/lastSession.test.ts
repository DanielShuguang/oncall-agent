import { describe, expect, it } from 'vitest';

import {
  LAST_SESSION_KEY,
  clearLastSession,
  readLastSession,
  writeLastSession,
} from './lastSession';

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

describe('lastSession', () => {
  it('reads a trimmed session id and rejects empty/oversized values', () => {
    const storage = new MemoryStorage();
    storage.setItem(LAST_SESSION_KEY, '  sess_a  ');
    expect(readLastSession(storage)).toBe('sess_a');

    storage.setItem(LAST_SESSION_KEY, '   ');
    expect(readLastSession(storage)).toBeNull();

    storage.setItem(LAST_SESSION_KEY, 's'.repeat(65));
    expect(readLastSession(storage)).toBeNull();
  });

  it('writes, normalizes and clears the remembered session', () => {
    const storage = new MemoryStorage();
    writeLastSession('  sess_a  ', storage);
    expect(readLastSession(storage)).toBe('sess_a');

    writeLastSession('   ', storage);
    expect(readLastSession(storage)).toBe('sess_a');

    clearLastSession(storage);
    expect(readLastSession(storage)).toBeNull();
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

    expect(readLastSession(storage)).toBeNull();
    expect(() => writeLastSession('sess_a', storage)).not.toThrow();
    expect(() => clearLastSession(storage)).not.toThrow();
  });
});
