/** 角色 × 工具权限矩阵（W5 D23）。 */

import { useEffect, useMemo, useState } from 'react';
import { RotateCcw, Save } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getPermMatrix, updatePermMatrix, type PermMatrix } from '@/api/perms';

interface Draft {
  enabled: boolean;
  roles: string[];
}

function toDraft(matrix: PermMatrix): Record<string, Draft> {
  return Object.fromEntries(
    matrix.tools.map((tool) => [tool.name, { enabled: tool.enabled, roles: [...tool.roles] }]),
  );
}

function normalize(draft: Record<string, Draft>, order: string[]): string {
  return JSON.stringify(
    order.map((name) => ({
      name,
      enabled: draft[name]?.enabled ?? false,
      // oxlint-disable-next-line unicorn/no-array-sort -- 排序的是副本，用于稳定比较
      roles: [...(draft[name]?.roles ?? [])].sort(),
    })),
  );
}

export default function PermsPage() {
  const [matrix, setMatrix] = useState<PermMatrix | null>(null);
  const [draft, setDraft] = useState<Record<string, Draft>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await getPermMatrix();
        if (cancelled) return;
        setMatrix(data);
        setDraft(toDraft(data));
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '权限矩阵加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const order = useMemo(() => matrix?.tools.map((tool) => tool.name) ?? [], [matrix]);
  const dirty = matrix !== null && normalize(draft, order) !== normalize(toDraft(matrix), order);

  const patch = (name: string, change: Partial<Draft>) => {
    setDraft((current) => ({
      ...current,
      [name]: { ...(current[name] ?? { enabled: false, roles: [] }), ...change },
    }));
    setNotice(null);
  };

  const allUsers = (name: string) => (draft[name]?.roles.length ?? 0) === 0;

  const toggleAllUsers = (name: string) => {
    if (!matrix) return;
    if (allUsers(name)) {
      // 取消「所有人」时先展开成当前目录的全部角色，再让用户逐个取消
      patch(name, { roles: [...matrix.roles] });
    } else {
      patch(name, { roles: [] });
    }
  };

  const toggleRole = (name: string, role: string) => {
    const current = draft[name];
    if (!current || current.roles.length === 0) return;
    if (current.roles.includes(role)) {
      if (current.roles.length === 1) {
        setError('至少保留一个角色；要停用请关闭「启用」开关');
        return;
      }
      patch(name, { roles: current.roles.filter((item) => item !== role) });
    } else {
      patch(name, { roles: [...current.roles, role] });
    }
    setError(null);
  };

  const resetTool = (name: string) => {
    const tool = matrix?.tools.find((item) => item.name === name);
    if (!tool) return;
    patch(name, { enabled: tool.default_enabled, roles: [...tool.default_roles] });
  };

  const resetAll = () => {
    if (!matrix) return;
    setDraft(
      Object.fromEntries(
        matrix.tools.map((tool) => [
          tool.name,
          { enabled: tool.default_enabled, roles: [...tool.default_roles] },
        ]),
      ),
    );
    setNotice('已填入代码默认值，点「保存矩阵」后生效。');
  };

  const save = async () => {
    if (!matrix) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updatePermMatrix(
        matrix.tools.map((tool) => ({
          name: tool.name,
          enabled: draft[tool.name]?.enabled ?? tool.enabled,
          roles: draft[tool.name]?.roles ?? tool.roles,
        })),
      );
      setMatrix(updated);
      setDraft(toDraft(updated));
      setNotice('权限矩阵已保存；下一次工具调用立即生效。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          勾选表示该角色可以调用；「所有人」等价于角色列表为空（新角色也会自动获得）。
          写操作即使勾选，也仍需人工审批（docs/06 §7）。
        </div>
        <Button variant="outline" size="sm" onClick={resetAll} disabled={!matrix}>
          <RotateCcw className="size-3.5" />
          填入默认值
        </Button>
        <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}>
          <Save className="size-3.5" />
          {saving ? '保存中…' : dirty ? '保存矩阵' : '无变更'}
        </Button>
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
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">工具</TableHead>
                <TableHead className="text-center text-xs">启用</TableHead>
                <TableHead className="text-center text-xs">所有人</TableHead>
                {matrix?.roles.map((role) => (
                  <TableHead key={role} className="text-center text-xs">
                    {role}
                  </TableHead>
                ))}
                <TableHead className="text-right text-xs">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {matrix?.tools.map((tool) => {
                const item = draft[tool.name];
                const everyone = allUsers(tool.name);
                return (
                  <TableRow key={tool.name}>
                    <TableCell className="max-w-72 align-top">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-medium">{tool.name}</span>
                        <Badge variant={tool.is_write ? 'destructive' : 'secondary'}>
                          {tool.is_write ? '写' : '读'}
                        </Badge>
                        {tool.overridden && (
                          <Badge variant="outline" className="text-[10px]">
                            已覆盖
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        {tool.description}
                      </div>
                      {!tool.code_enabled && (
                        <div className="mt-1 text-[11px] text-warn">代码中已禁用，不可开启</div>
                      )}
                    </TableCell>
                    <TableCell className="text-center align-top">
                      <input
                        type="checkbox"
                        className="size-4 accent-brand"
                        aria-label={`${tool.name} 启用`}
                        checked={item?.enabled ?? false}
                        disabled={!tool.code_enabled}
                        onChange={(event) => patch(tool.name, { enabled: event.target.checked })}
                      />
                    </TableCell>
                    <TableCell className="text-center align-top">
                      <input
                        type="checkbox"
                        className="size-4 accent-brand"
                        aria-label={`${tool.name} 允许所有登录用户`}
                        checked={everyone}
                        onChange={() => toggleAllUsers(tool.name)}
                      />
                    </TableCell>
                    {matrix.roles.map((role) => {
                      const checked = everyone || (item?.roles.includes(role) ?? false);
                      return (
                        <TableCell key={role} className="text-center align-top">
                          <input
                            type="checkbox"
                            className="size-4 accent-brand"
                            aria-label={`${tool.name} 允许 ${role}`}
                            checked={checked}
                            disabled={everyone}
                            onChange={() => toggleRole(tool.name, role)}
                          />
                        </TableCell>
                      );
                    })}
                    <TableCell className="text-right align-top">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={!tool.overridden}
                        onClick={() => resetTool(tool.name)}
                      >
                        默认
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        保存是整份矩阵替换：提交后不在列表里的角色会被移除，但没提交的工具保持原样。 代码里{' '}
        <code>enabled=False</code> 的工具只能保持禁用，管理页不能绕过。
      </p>
    </div>
  );
}
