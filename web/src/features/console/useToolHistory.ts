/** 工具变更历史的加载、分页与导出；列表/导出共用同一「已应用」日期窗口。 */

import { useRef, useState } from 'react';
import { ApiError } from '@/api/client';
import {
  exportToolHistoryCsv,
  getToolHistory,
  type ToolHistoryOrder,
  type ToolInfo,
} from '@/api/tools';
import { downloadBlob } from '@/lib/download';
import type { HistoryState } from './ToolsDialogs';

export function useToolHistory() {
  const [history, setHistory] = useState<HistoryState | null>(null);
  const [exportingHistory, setExportingHistory] = useState(false);
  const [historyExportMessage, setHistoryExportMessage] = useState<string | null>(null);
  const historyRequest = useRef(0);
  const historyExportRequest = useRef(0);

  const requestHistory = (
    tool: ToolInfo,
    changedFrom: string,
    changedTo: string,
    changedBy: string,
    source: '' | 'tool' | 'matrix' | 'rollback',
    order: ToolHistoryOrder = 'latest',
  ) => {
    const requestId = ++historyRequest.current;
    historyExportRequest.current += 1;
    setExportingHistory(false);
    setHistoryExportMessage(null);
    setHistory({
      tool,
      loading: true,
      items: [],
      error: null,
      changedFrom,
      changedTo,
      changedBy,
      source,
      order,
      filterError: null,
      appliedFrom: changedFrom,
      appliedTo: changedTo,
      appliedBy: changedBy,
      appliedSource: source,
      appliedOrder: order,
      total: null,
      nextCursor: null,
      loadingMore: false,
      loadMoreError: null,
      loadMoreErrorCode: null,
      selectedIds: [],
    });
    void (async () => {
      try {
        const data = await getToolHistory(tool.name, 20, {
          changedFrom,
          changedTo,
          changedBy,
          source,
          order,
        });
        if (requestId !== historyRequest.current) return;
        setHistory((current) =>
          current?.tool.name === tool.name
            ? {
                ...current,
                loading: false,
                items: data.items,
                total: data.total ?? null,
                nextCursor: data.next_cursor ?? null,
                error: null,
              }
            : current,
        );
      } catch (exc) {
        if (requestId !== historyRequest.current) return;
        setHistory((current) =>
          current?.tool.name === tool.name
            ? {
                ...current,
                loading: false,
                error: exc instanceof Error ? exc.message : '变更历史加载失败',
              }
            : current,
        );
      }
    })();
  };

  const openHistory = (tool: ToolInfo) => requestHistory(tool, '', '', '', '', 'latest');

  const loadMoreHistory = () => {
    if (!history || !history.nextCursor || history.loadingMore) return;
    const requestId = ++historyRequest.current;
    const tool = history.tool;
    const cursor = history.nextCursor;
    const from = history.appliedFrom;
    const to = history.appliedTo;
    const by = history.appliedBy;
    const source = history.appliedSource;
    const order = history.appliedOrder;
    setHistory((current) =>
      current?.tool.name === tool.name
        ? {
            ...current,
            loadingMore: true,
            filterError: null,
            loadMoreError: null,
            loadMoreErrorCode: null,
          }
        : current,
    );
    void (async () => {
      try {
        const data = await getToolHistory(
          tool.name,
          20,
          { changedFrom: from, changedTo: to, changedBy: by, source, order },
          cursor,
        );
        if (requestId !== historyRequest.current) return;
        setHistory((current) =>
          current?.tool.name === tool.name
            ? {
                ...current,
                loadingMore: false,
                loadMoreError: null,
                loadMoreErrorCode: null,
                items: [...current.items, ...data.items],
                nextCursor: data.next_cursor ?? null,
              }
            : current,
        );
      } catch (exc) {
        if (requestId !== historyRequest.current) return;
        setHistory((current) =>
          current?.tool.name === tool.name
            ? {
                ...current,
                loadingMore: false,
                loadMoreError: exc instanceof Error ? exc.message : '加载更多失败',
                loadMoreErrorCode: exc instanceof ApiError ? exc.code : null,
              }
            : current,
        );
      }
    })();
  };

  const reloadHistory = () => {
    if (!history) return;
    const from = history.changedFrom;
    const to = history.changedTo;
    if ((from && !to) || (!from && to)) {
      // 过滤校验失败时同时清掉上一次「加载更多」的错误，避免旧游标过期提示
      // 和新的日期错误同时挂在 Dialog 里。
      setHistory({
        ...history,
        filterError: '开始日期与结束日期必须同时选择',
        loadMoreError: null,
        loadMoreErrorCode: null,
      });
      return;
    }
    if (from && to && from > to) {
      setHistory({
        ...history,
        filterError: '开始日期不能晚于结束日期',
        loadMoreError: null,
        loadMoreErrorCode: null,
      });
      return;
    }
    requestHistory(history.tool, from, to, history.changedBy, history.source, history.order);
  };

  const reloadExpiredHistory = () => {
    if (!history) return;
    // 过期后重新取第一页，必须用「已应用」筛选；草稿可能尚未应用。
    requestHistory(
      history.tool,
      history.appliedFrom,
      history.appliedTo,
      history.appliedBy,
      history.appliedSource,
      history.appliedOrder,
    );
  };

  const clearHistoryFilters = () => {
    if (history) requestHistory(history.tool, '', '', '', '', 'latest');
  };

  const closeHistory = () => {
    historyExportRequest.current += 1;
    setExportingHistory(false);
    setHistoryExportMessage(null);
    setHistory(null);
  };

  const exportHistory = async () => {
    if (!history) return;
    const requestId = ++historyExportRequest.current;
    setExportingHistory(true);
    setHistoryExportMessage(null);
    try {
      const result = await exportToolHistoryCsv(history.tool.name, {
        changedFrom: history.appliedFrom,
        changedTo: history.appliedTo,
        changedBy: history.appliedBy,
        source: history.appliedSource,
        order: history.appliedOrder,
      });
      if (requestId !== historyExportRequest.current) return;
      downloadBlob(result.blob, `tool-history-${history.tool.name}.csv`);
      setHistoryExportMessage(
        result.truncated
          ? `已导出前 ${result.count} 条（窗口内记录更多，已截断）`
          : `已导出 ${result.count} 条`,
      );
    } catch (exc) {
      if (requestId !== historyExportRequest.current) return;
      setHistoryExportMessage(exc instanceof Error ? exc.message : '导出失败');
    } finally {
      if (requestId === historyExportRequest.current) setExportingHistory(false);
    }
  };

  const clearHistorySelection = () => {
    setHistory((current) =>
      current && current.selectedIds.length > 0 ? { ...current, selectedIds: [] } : current,
    );
  };

  const toggleHistorySelection = (changeId: number) => {
    setHistory((current) => {
      if (!current) return current;
      const selected = current.selectedIds.includes(changeId)
        ? current.selectedIds.filter((id) => id !== changeId)
        : [...current.selectedIds, changeId];
      return { ...current, selectedIds: selected };
    });
  };

  return {
    history,
    setHistory,
    exportingHistory,
    historyExportMessage,
    openHistory,
    reloadHistory,
    clearHistoryFilters,
    loadMoreHistory,
    reloadExpiredHistory,
    closeHistory,
    exportHistory,
    clearHistorySelection,
    toggleHistorySelection,
  };
}
