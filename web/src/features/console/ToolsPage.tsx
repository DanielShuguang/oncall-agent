/** 工具注册与试调用（W5 D22）。schema 只读，启用/角色走治理配置。 */

import { useEffect, useState } from 'react';
import { FlaskConical, History, Lock, RotateCcw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import {
  exampleArgs,
  getToolHistory,
  listTools,
  testTool,
  updateTool,
  type ToolChange,
  type ToolInfo,
  type ToolOverrideSnapshot,
  type ToolTestResponse,
} from '@/api/tools';

interface TestState {
  tool: ToolInfo;
  argsText: string;
  running: boolean;
  result: ToolTestResponse | null;
  error: string | null;
}

interface HistoryState {
  tool: ToolInfo;
  loading: boolean;
  items: ToolChange[];
  error: string | null;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function describeSnapshot(snapshot: ToolOverrideSnapshot | null): string {
  if (snapshot === null) return '代码默认';
  const enabled = snapshot.enabled === null ? '启用继承' : snapshot.enabled ? '启用' : '禁用';
  const roles =
    snapshot.roles === null
      ? '角色继承'
      : snapshot.roles.length === 0
        ? '所有登录用户'
        : snapshot.roles.join('、');
  return `${enabled} · ${roles}`;
}

function sourceLabel(source: string): string {
  if (source === 'matrix') return '权限矩阵';
  if (source === 'tool') return '工具开关';
  return source;
}

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tester, setTester] = useState<TestState | null>(null);
  const [history, setHistory] = useState<HistoryState | null>(null);

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

  const openHistory = (tool: ToolInfo) => {
    setHistory({ tool, loading: true, items: [], error: null });
    void (async () => {
      try {
        const data = await getToolHistory(tool.name);
        setHistory((current) =>
          current?.tool.name === tool.name
            ? { ...current, loading: false, items: data.items }
            : current,
        );
      } catch (exc) {
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

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>工具</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>超时</TableHead>
                    <TableHead>允许角色</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tools.map((tool) => (
                    <TableRow key={tool.name}>
                      <TableCell className="max-w-80 align-top">
                        <div className="font-mono text-xs font-medium">{tool.name}</div>
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {tool.description}
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={tool.is_write ? 'destructive' : 'secondary'}>
                          {tool.is_write ? '写操作' : '只读'}
                        </Badge>
                      </TableCell>
                      <TableCell className="align-top text-xs text-muted-foreground">
                        {tool.timeout_ms}ms
                      </TableCell>
                      <TableCell className="max-w-56 align-top text-xs">
                        {tool.roles.length === 0 ? (
                          <span className="text-muted-foreground">所有登录用户</span>
                        ) : (
                          <span className="font-mono">{tool.roles.join(' / ')}</span>
                        )}
                        {tool.overridden && (
                          <Badge variant="outline" className="ml-2 text-[10px]">
                            已覆盖
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        {!tool.code_enabled ? (
                          <Badge variant="outline" className="text-muted-foreground">
                            <Lock className="size-3" /> 代码禁用
                          </Badge>
                        ) : tool.enabled ? (
                          <Badge variant="outline" className="border-ok/30 text-ok">
                            启用
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="border-danger/30 text-danger">
                            已禁用
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right align-top">
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => openHistory(tool)}
                          >
                            <History className="size-3" />
                            历史
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => openTester(tool)}
                          >
                            <FlaskConical className="size-3" />
                            试调用
                          </Button>
                          {tool.code_enabled && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              disabled={busy === tool.name}
                              onClick={() => void onToggle(tool)}
                            >
                              {tool.enabled ? '禁用' : '启用'}
                            </Button>
                          )}
                          {tool.overridden && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs"
                              disabled={busy === tool.name}
                              title="撤销启用覆盖，角色覆盖保留"
                              onClick={() => void onReset(tool)}
                            >
                              <RotateCcw className="size-3" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        角色矩阵在「权限」页编辑。工具 schema 由代码定义，避免在线修改让入参校验与提示词脱节；
        需要新工具时走 code review 与治理测试（docs/06）。每次真正改变启用/角色的管理写入都会
        记入「历史」（谁、何时、从什么改成什么），长期保留。
      </p>

      <Dialog
        open={tester !== null}
        onOpenChange={(open) => {
          if (!open) setTester(null);
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">{tester?.tool.name}</DialogTitle>
            <DialogDescription>
              {tester?.tool.description}
              {tester?.tool.is_write
                ? ' · 写操作：试调用只验证审批闸门，不会真正执行'
                : ' · 只读：会真实执行 handler'}
            </DialogDescription>
          </DialogHeader>

          <div>
            <div className="mb-1 text-xs text-muted-foreground">参数（JSON）</div>
            <Textarea
              rows={8}
              aria-label="试调用参数"
              className="font-mono text-xs"
              value={tester?.argsText ?? ''}
              disabled={tester?.running}
              onChange={(event) => {
                if (tester) setTester({ ...tester, argsText: event.target.value });
              }}
            />
            <details className="mt-2 text-[11px] text-muted-foreground">
              <summary className="cursor-pointer select-none">查看只读 schema</summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-canvas/50 p-2 font-mono text-[11px] whitespace-pre-wrap">
                {JSON.stringify(tester?.tool.input_schema ?? {}, null, 2)}
              </pre>
            </details>
          </div>

          {tester?.error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {tester.error}
            </div>
          )}

          {tester?.result && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant={tester.result.status === 'ok' ? 'secondary' : 'destructive'}>
                  {tester.result.status}
                </Badge>
                <span className="text-muted-foreground">
                  decision={tester.result.decision} · {tester.result.duration_ms}ms · 尝试{' '}
                  {tester.result.attempts} 次
                </span>
              </div>
              {tester.result.error && (
                <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
                  {tester.result.error}
                  {tester.result.error_kind ? `（${tester.result.error_kind}）` : ''}
                </div>
              )}
              <pre className="max-h-64 overflow-auto rounded-md border bg-panel p-3 font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(tester.result.result, null, 2)}
              </pre>
              {tester.result.decision === 'requires_approval' && (
                <p className="text-[11px] text-muted-foreground">
                  真实对话里会生成审批卡；审批人通过后才执行 handler。
                </p>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setTester(null)}>
              关闭
            </Button>
            <Button disabled={tester?.running} onClick={() => void runTest()}>
              {tester?.running ? '执行中…' : '执行'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={history !== null}
        onOpenChange={(open) => {
          if (!open) setHistory(null);
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">变更历史 · {history?.tool.name}</DialogTitle>
            <DialogDescription>
              只记录管理页真正改变配置的写入；试调用与运行中的工具调用不会产生记录。
            </DialogDescription>
          </DialogHeader>

          {history?.loading ? (
            <div className="p-6 text-center text-xs text-muted-foreground">加载中…</div>
          ) : history?.error ? (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {history.error}
            </div>
          ) : history && history.items.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              还没有配置变更记录。
            </div>
          ) : (
            <div className="max-h-96 space-y-2 overflow-auto">
              {history?.items.map((item) => (
                <div key={item.id} className="rounded-md border p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{sourceLabel(item.source)}</Badge>
                    <span className="text-muted-foreground">{formatTime(item.changed_at)}</span>
                    <span className="font-mono">{item.changed_by}</span>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {describeSnapshot(item.before)} → {describeSnapshot(item.after)}
                  </div>
                </div>
              ))}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setHistory(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
