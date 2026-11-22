import { describe, expect, it } from 'vitest';
import { EMPTY_EXPORT_AUDIT_DRAFT, toExportAuditFilters } from './exportAuditDraft';

describe('toExportAuditFilters', () => {
  it('trims the user and keeps resource/date values', () => {
    expect(
      toExportAuditFilters({
        userId: '  u_102  ',
        resource: 'approvals',
        createdFrom: '2026-11-01',
        createdTo: '2026-11-02',
      }),
    ).toEqual({
      userId: 'u_102',
      resource: 'approvals',
      createdFrom: '2026-11-01',
      createdTo: '2026-11-02',
    });
  });

  it('omits empty strings instead of sending them', () => {
    expect(toExportAuditFilters(EMPTY_EXPORT_AUDIT_DRAFT)).toEqual({});
  });

  it('does not invent a date range when only a user is provided', () => {
    expect(toExportAuditFilters({ ...EMPTY_EXPORT_AUDIT_DRAFT, userId: 'u_102' })).toEqual({
      userId: 'u_102',
    });
  });
});
