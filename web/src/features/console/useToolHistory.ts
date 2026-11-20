/** 工具变更历史的加载、分页与导出；列表/导出共用同一「已应用」日期窗口。 */

import { useRef, useState } from 'react';
import { exportToolHistoryCsv, getToolHistory, type ToolInfo } from '@/api/tools';
import { downloadBlob } from '@/lib/download';
import type { HistoryState } from './ToolsDialogs';

export function useToolHistory() {
  const [history, setHistory] = useState<HistoryState | null>(null);
  const [exportingHistory, setExportingHistory] = useState(false);
  const [historyExportMessage, setHistoryExportMessage] = useState<string | null>(null);
  const historyRequest = useRef(0);
  const historyExportRequest = useRef(0);

  const requestHistory = (tool: ToolInfo, changedFrom: string, changedTo: string) => {
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
      filterError: null,
      appliedFrom: changedFrom,
      appliedTo: changedTo,
      total: null,
      nextCursor: null,
      loadingMore: false,
      loadMoreError: null,
    });
    void (async () => {
      try {
        const data = await getToolHistory(tool.name, 20, { changedFrom, changedTo });
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

  const openHistory = (tool: ToolInfo) => requestHistory(tool, '', '');

  const loadMoreHistory = () => {
    if (!history || !history.nextCursor || history.loadingMore) return;
    const requestId = ++historyRequest.current;
    const tool = history.tool;
    const cursor = history.nextCursor;
    const from = history.appliedFrom;
    const to = history.appliedTo;
    setHistory((current) =>
      current?.tool.name === tool.name
        ? { ...current, loadingMore: true, filterError: null, loadMoreError: null }
        : current,
    );
    void (async () => {
      try {
        const data = await getToolHistory(
          tool.name,
          20,
          { changedFrom: from, changedTo: to },
          cursor,
        );
        if (requestId !== historyRequest.current) return;
        setHistory((current) =>
          current?.tool.name === tool.name
            ? {
                ...current,
                loadingMore: false,
                loadMoreError: null,
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
      setHistory({ ...history, filterError: '开始日期与结束日期必须同时选择' });
      return;
    }
    if (from && to && from > to) {
      setHistory({ ...history, filterError: '开始日期不能晚于结束日期' });
      return;
    }
    requestHistory(history.tool, from, to);
  };

  const clearHistoryFilters = () => {
    if (history) requestHistory(history.tool, '', '');
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

  return {
    history,
    setHistory,
    exportingHistory,
    historyExportMessage,
    openHistory,
    reloadHistory,
    clearHistoryFilters,
    loadMoreHistory,
    closeHistory,
    exportHistory,
  };
}
