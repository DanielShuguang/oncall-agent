import { describe, expect, it } from 'vitest';
import { mergeBudgetRows } from './budgetRows';

const usage = (user_id: string, spent_cents: number) => ({
  user_id,
  spent_cents,
  reserved_cents: spent_cents,
  reservation_count: 1,
  stale_count: 0,
  stale_cents: 0,
  oldest_age_s: 1,
});

describe('mergeBudgetRows', () => {
  it('merges overrides with usage and keeps the default limit', () => {
    const rows = mergeBudgetRows(
      [
        {
          user_id: 'u_2',
          daily_cents: 100,
          updated_by: 'admin_1',
          updated_at: '2026-11-11T00:00:00Z',
        },
      ],
      0,
      [usage('u_1', 7), usage('u_2', 3)],
    );

    expect(rows.map((row) => row.user_id)).toEqual(['u_1', 'u_2']);
    expect(rows[0]).toMatchObject({
      spent_cents: 7,
      daily_cents: 0,
      source: 'default',
      updated_by: null,
    });
    expect(rows[1]).toMatchObject({
      spent_cents: 3,
      daily_cents: 100,
      source: 'override',
      updated_by: 'admin_1',
    });
  });

  it('uses null instead of zero when usage or the default is unknown', () => {
    const rows = mergeBudgetRows([], null, null);
    expect(rows).toEqual([]);

    const withOverride = mergeBudgetRows(
      [{ user_id: 'u_2', daily_cents: 50, updated_by: 'admin_1', updated_at: null }],
      null,
      null,
    );
    expect(withOverride[0]).toMatchObject({
      spent_cents: null,
      daily_cents: 50,
      source: 'override',
    });
  });
});
