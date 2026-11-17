import { useState, type Dispatch, type SetStateAction } from 'react';
import {
  hideSession,
  hideSessions as hideSessionsBatch,
  type SessionSummary,
} from '@/api/sessions';

interface Args {
  sessionId: string | null;
  sessions: SessionSummary[];
  batchHideSelected: Set<string>;
  setBatchHideSelected: Dispatch<SetStateAction<Set<string>>>;
  refreshSessions: () => void;
  setSessionsError: (message: string | null) => void;
}

export interface HideResult {
  ok: boolean;
  current: boolean;
}

export function useSessionMutations({
  sessionId,
  sessions,
  batchHideSelected,
  setBatchHideSelected,
  refreshSessions,
  setSessionsError,
}: Args) {
  // 正在从会话列表移除的会话（ADR-0041）；移除只影响列表，不删 run
  const [hidingId, setHidingId] = useState<string | null>(null);
  // 批量移除（ADR-0072）：管理模式下按当前已加载页选择
  const [batchHideMode, setBatchHideMode] = useState(false);
  const [batchHiding, setBatchHiding] = useState(false);
  const [batchHideNotice, setBatchHideNotice] = useState<string | null>(null);

  const onHideSession = async (targetSessionId: string): Promise<HideResult> => {
    if (hidingId) return { ok: false, current: false };
    setHidingId(targetSessionId);
    setSessionsError(null);
    try {
      await hideSession(targetSessionId);
      refreshSessions();
      return { ok: true, current: targetSessionId === sessionId };
    } catch (err) {
      setSessionsError(err instanceof Error ? err.message : '会话移除失败');
      return { ok: false, current: false };
    } finally {
      setHidingId(null);
    }
  };

  const onToggleBatchHide = () => {
    if (batchHideMode) {
      setBatchHideMode(false);
      setBatchHideNotice(null);
    } else {
      setBatchHideMode(true);
    }
    setBatchHideSelected(new Set());
  };

  const onBatchHideToggleSelect = (targetSessionId: string) => {
    setBatchHideSelected((prev) => {
      const next = new Set(prev);
      if (next.has(targetSessionId)) next.delete(targetSessionId);
      else next.add(targetSessionId);
      return next;
    });
  };

  const onBatchHideToggleAll = () => {
    setBatchHideSelected((prev) => {
      const allSelected =
        sessions.length > 0 && sessions.every((item) => prev.has(item.session_id));
      return allSelected ? new Set() : new Set(sessions.map((item) => item.session_id));
    });
  };

  const onHideSelectedSessions = async (): Promise<HideResult> => {
    if (batchHiding || batchHideSelected.size === 0) return { ok: false, current: false };
    const ids = [...batchHideSelected];
    setBatchHiding(true);
    setSessionsError(null);
    setBatchHideNotice(null);
    try {
      const result = await hideSessionsBatch(ids);
      setBatchHideMode(false);
      setBatchHideSelected(new Set());
      const failed = result.items.filter((item) => !item.hidden).length;
      setBatchHideNotice(
        result.hidden === 0
          ? `没有会话被移除${failed > 0 ? `（${failed} 个不存在或不属于你）` : ''}。`
          : failed > 0
            ? `已移除 ${result.hidden} 个会话；${failed} 个未移除（可能不存在或不属于你）。`
            : `已移除 ${result.hidden} 个会话。`,
      );
      refreshSessions();
      return { ok: true, current: ids.includes(sessionId ?? '') };
    } catch (err) {
      setSessionsError(err instanceof Error ? err.message : '批量移除失败');
      return { ok: false, current: false };
    } finally {
      setBatchHiding(false);
    }
  };

  return {
    hidingId,
    batchHideMode,
    batchHideSelected,
    batchHiding,
    batchHideNotice,
    onHideSession,
    onToggleBatchHide,
    onBatchHideToggleSelect,
    onBatchHideToggleAll,
    onHideSelectedSessions,
  };
}
