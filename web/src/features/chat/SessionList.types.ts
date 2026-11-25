import type { HiddenSession, SessionSummary } from '@/api/sessions';

export interface SessionListProps {
  sessions: SessionSummary[];
  activeSessionId: string;
  /** 窄屏抽屉是否打开（ADR-0076）；≥sm 时侧栏常驻，不受此值影响 */
  mobileOpen: boolean;
  onCloseMobile: () => void;
  loading: boolean;
  error: string | null;
  /** 历史会话正在加载：暂时锁住列表项，避免连点导致后到的响应覆盖前一次选择 */
  busy: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  /** 已提交的搜索词（ADR-0039），只用于空态文案 */
  query: string;
  searchDraft: string;
  onSearchDraftChange: (value: string) => void;
  onSearch: () => void;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
  /** 正在改名的会话（ADR-0040）；null 表示没有行内编辑 */
  renamingId: string | null;
  renameDraft: string;
  renameSaving: boolean;
  onRenameStart: (session: SessionSummary) => void;
  onRenameDraftChange: (value: string) => void;
  onRenameSubmit: () => void;
  onRenameCancel: () => void;
  /** 正在置顶/取消置顶的会话（ADR-0069） */
  pinningId: string | null;
  pinnedCount: number | null;
  pinLimit: number | null;
  onTogglePin: (session: SessionSummary) => void;
  /** 正在从列表移除的会话（ADR-0041） */
  hidingId: string | null;
  onHide: (sessionId: string) => void;
  /** 批量移除（ADR-0072）：管理模式下多选当前已加载页 */
  batchMode: boolean;
  batchSelected: Set<string>;
  batchHiding: boolean;
  batchNotice: string | null;
  onToggleBatchMode: () => void;
  onBatchToggleSelect: (sessionId: string) => void;
  onBatchToggleAll: () => void;
  onHideSelected: () => void;
  /** 已移除的会话折叠区（ADR-0043） */
  hiddenOpen: boolean;
  hiddenSessions: HiddenSession[];
  hiddenTotal: number | null;
  hiddenLoading: boolean;
  hiddenError: string | null;
  /** 批量恢复后的部分成功提示（ADR-0055）；不占用错误样式 */
  hiddenNotice: string | null;
  /** 已移除视图的搜索与分页（ADR-0047） */
  hiddenQuery: string;
  hiddenDraftQuery: string;
  hiddenHasMore: boolean;
  hiddenLoadingMore: boolean;
  onHiddenDraftChange: (value: string) => void;
  onHiddenSearch: () => void;
  onHiddenLoadMore: () => void;
  restoringId: string | null;
  /** 批量恢复（ADR-0049）：选中只覆盖当前已加载页 */
  restoringBatch: boolean;
  hiddenSelected: Set<string>;
  onHiddenToggleSelect: (sessionId: string) => void;
  onHiddenToggleAll: () => void;
  onRestoreSelected: () => void;
  onToggleHidden: () => void;
  onRestore: (sessionId: string) => void;
}
