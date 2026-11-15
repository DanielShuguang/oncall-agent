import { describe, expect, it } from 'vitest';
import { shouldClearLocalPreferences, tokenSubject } from './tokenSubject';

describe('tokenSubject', () => {
  it('读取 JWT payload 里的 sub，并去掉首尾空白', () => {
    expect(tokenSubject(makeToken({ sub: '  u_102  ' }))).toBe('u_102');
  });

  it('没有 sub / sub 不是非空字符串时返回 null', () => {
    expect(tokenSubject(makeToken({}))).toBeNull();
    expect(tokenSubject(makeToken({ sub: 42 }))).toBeNull();
    expect(tokenSubject(makeToken({ sub: '   ' }))).toBeNull();
  });

  it('非 JWT、坏 base64 或坏 JSON 返回 null', () => {
    expect(tokenSubject(null)).toBeNull();
    expect(tokenSubject('only-one-part')).toBeNull();
    expect(tokenSubject('a.b.c')).toBeNull();
    expect(tokenSubject(`a.${btoa('not json')}.c`)).toBeNull();
  });

  it('只在新 token 有 subject 且换人时要求清理', () => {
    const a = makeToken({ sub: 'u_a' });
    const aReissued = makeToken({ sub: 'u_a', exp: 1 });
    const b = makeToken({ sub: 'u_b' });

    expect(shouldClearLocalPreferences(null, a)).toBe(true);
    expect(shouldClearLocalPreferences('not-a-jwt', a)).toBe(true);
    expect(shouldClearLocalPreferences(a, b)).toBe(true);
    expect(shouldClearLocalPreferences(a, aReissued)).toBe(false);
    expect(shouldClearLocalPreferences(a, a)).toBe(false);
    expect(shouldClearLocalPreferences(a, '')).toBe(false);
    expect(shouldClearLocalPreferences(null, null)).toBe(false);
    expect(shouldClearLocalPreferences(a, 'not-a-jwt')).toBe(false);
  });
});

function makeToken(payload: unknown): string {
  const encoded = btoa(JSON.stringify(payload))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '');
  return `eyJhbGciOiJIUzI1NiJ9.${encoded}.signature`;
}
