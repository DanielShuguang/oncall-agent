import { describe, expect, it } from 'vitest';

import { auditDatePresetRange } from './auditDatePresets';

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
