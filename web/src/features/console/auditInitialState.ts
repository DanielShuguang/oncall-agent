import type { SessionRestoreAuditFilters } from '@/api/sessionAudits';
import {
  auditDatePresetRange,
  readLastAuditDatePreset,
  type AuditDatePreset,
} from './auditDatePresets';
import { readAuditFilterMemory, type AuditStatsDays } from './auditFilterMemory';

interface InitialAuditState {
  preset: AuditDatePreset | null;
  range: { from: string; to: string } | null;
  statsDays: AuditStatsDays;
  userId: string;
  sessionId: string;
  filters: SessionRestoreAuditFilters;
}

export function readInitialAuditState(): InitialAuditState {
  const preset = readLastAuditDatePreset();
  const range = preset ? auditDatePresetRange(preset) : null;
  const memory = readAuditFilterMemory();
  const userId = memory?.userId ?? '';
  const sessionId = memory?.sessionId ?? '';
  return {
    preset,
    range,
    statsDays: memory?.statsDays ?? 30,
    userId,
    sessionId,
    filters: {
      ...(userId ? { userId } : {}),
      ...(sessionId ? { sessionId } : {}),
      ...(range ? { restoredFrom: range.from, restoredTo: range.to } : {}),
    } satisfies SessionRestoreAuditFilters,
  };
}
