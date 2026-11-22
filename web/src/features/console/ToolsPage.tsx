/** 工具注册与试调用（W5 D22）。schema 只读，启用/角色走治理配置。 */

import { useEffect, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import {
  exampleArgs,
  listTools,
  rollbackToolChange,
  testTool,
  updateTool,
  type ToolInfo,
} from '@/api/tools';
import { ToolsDialogs, type TestState } from './ToolsDialogs';
import { ToolsTable } from './ToolsTable';
import { useToolHistory } from './useToolHistory';

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rollingBackId, setRollingBackId] = useState<number | null>(null);
  const [rollbackMessage, setRollbackMessage] = useState<string | null>(null);
  const [tester, setTester] = useState<TestState | null>(null);
  const {
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
  } = useToolHistory();
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await listTools();
        if (!cancelled) setTools(data.items);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '工具列表加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = async () => {
    const data = await listTools();
    setTools(data.items);
  };

  const onToggle = async (tool: ToolInfo) => {
    setBusy(tool.name);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateTool(tool.name, { enabled: !tool.enabled });
      setTools((current) => current.map((item) => (item.name === updated.name ? updated : item)));
      setNotice(`${updated.name} 已${updated.enabled ? '启用' : '禁用'}；下一次工具调用立即生效。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败');
    } finally {
      setBusy(null);
    }
  };

  const onRollback = async (changeId: number) => {
    if (!history) return;
    if (!window.confirm('将工具配置回滚到该变更发生前的状态？')) return;
    setRollingBackId(changeId);
    setRollbackMessage(null);
    try {
      const updated = await rollbackToolChange(history.tool.name, changeId);
      setTools((current) => current.map((item) => (item.name === updated.name ? updated : item)));
      setNotice(`${updated.name} 已回滚；下一次工具调用立即生效。`);
      setRollbackMessage('已回滚，历史中新增一条回滚记录。');
      await reloadHistory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '回滚失败');
    } finally {
      setRollingBackId(null);
    }
  };
  const onReset = async (tool: ToolInfo) => {
    setBusy(tool.name);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateTool(tool.name, { enabled: null });
      setTools((current) => current.map((item) => (item.name === updated.name ? updated : item)));
      setNotice(`${updated.name} 已恢复代码默认的启用状态（角色覆盖不受影响）。`);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败');
    } finally {
      setBusy(null);
    }
  };

  const openTester = (tool: ToolInfo) => {
    setTester({
      tool,
      argsText: JSON.stringify(exampleArgs(tool.input_schema), null, 2),
      running: false,
      result: null,
      error: null,
    });
  };

  const runTest = async () => {
    if (!tester) return;
    let args: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(tester.argsText || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('参数必须是 JSON 对象');
      }
      args = parsed as Record<string, unknown>;
    } catch (exc) {
      setTester({ ...tester, error: exc instanceof Error ? exc.message : 'JSON 解析失败' });
      return;
    }

    setTester({ ...tester, running: true, error: null, result: null });
    try {
      const result = await testTool(tester.tool.name, args);
      setTester((current) => (current ? { ...current, running: false, result } : current));
    } catch (exc) {
      setTester((current) =>
        current
          ? {
              ...current,
              running: false,
              error: exc instanceof Error ? exc.message : '试调用失败',
            }
          : current,
      );
    }
  };

  return (
    <div className="space-y-4">
      <div className="text-xs text-muted-foreground">
        工具定义（schema、是否写操作、超时）在代码里，管理页只读；可改的是本环境的启用状态与角色。
        试调用强制走 <code>ToolGuard</code>，写操作只会返回「需要审批」，不会真的落单。
      </div>

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{error}</CardContent>
        </Card>
      )}
      {notice && (
        <Card className="border-ok/30 bg-ok/5">
          <CardContent className="p-3 text-xs text-ok">{notice}</CardContent>
        </Card>
      )}

      <ToolsTable
        tools={tools}
        loading={loading}
        busy={busy}
        onToggle={(tool) => void onToggle(tool)}
        onReset={(tool) => void onReset(tool)}
        onTest={openTester}
        onHistory={openHistory}
      />

      <p className="text-[11px] text-muted-foreground">
        角色矩阵在「权限」页编辑。工具 schema 由代码定义，避免在线修改让入参校验与提示词脱节；
        需要新工具时走 code review 与治理测试（docs/06）。每次真正改变启用/角色的管理写入都会
        记入「历史」（谁、何时、从什么改成什么），长期保留。
      </p>

      <ToolsDialogs
        tester={tester}
        history={history}
        onTesterChange={setTester}
        onHistoryChange={(next) => (next ? setHistory(next) : closeHistory())}
        onReloadHistory={reloadHistory}
        onClearHistoryFilters={clearHistoryFilters}
        onLoadMoreHistory={loadMoreHistory}
        onReloadExpiredHistory={reloadExpiredHistory}
        onRollbackHistory={onRollback}
        rollingBackId={rollingBackId}
        rollbackMessage={rollbackMessage}
        onExportHistory={() => void exportHistory()}
        exportingHistory={exportingHistory}
        historyExportMessage={historyExportMessage}
        onRunTest={() => void runTest()}
      />
    </div>
  );
}
