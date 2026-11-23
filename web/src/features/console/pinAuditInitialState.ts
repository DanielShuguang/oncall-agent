import type { SessionPinAuditFilters } from '@/api/pinAudits';
import {
  auditDatePresetRange,
  PIN_AUDIT_DATE_PRESET_STORAGE_KEY,
  readAuditDatePresetFor,
} from './auditDatePresets';
import { readPinAuditFilterMemory } from './auditPageFilterMemory';
import { EMPTY_PIN_AUDIT_DRAFT, type PinAuditDraft } from './PinAuditFilterCard';

export function initialPinAuditState(): {
  filters: SessionPinAuditFilters;
  draft: PinAuditDraft;
} {
  const preset = readAuditDatePresetFor(PIN_AUDIT_DATE_PRESET_STORAGE_KEY);
  const range = preset ? auditDatePresetRange(preset) : null;
  const memory = readPinAuditFilterMemory();
  if (!range && !memory) return { filters: {}, draft: EMPTY_PIN_AUDIT_DRAFT };
  return {
    filters: {
      ...(memory?.userId ? { userId: memory.userId } : {}),
      ...(memory?.sessionId ? { sessionId: memory.sessionId } : {}),
      ...(memory && memory.action !== 'all' ? { action: memory.action } : {}),
      ...(range ? { createdFrom: range.from, createdTo: range.to } : {}),
    },
    draft: {
      ...EMPTY_PIN_AUDIT_DRAFT,
      ...(memory
        ? { userId: memory.userId, sessionId: memory.sessionId, action: memory.action }
        : {}),
      ...(range ? { from: range.from, to: range.to } : {}),
    },
  };
}
