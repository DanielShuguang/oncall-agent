/** 个人日预算（ADR-0026）：默认值 + 按用户覆盖，单位「分」，0 = 不限。 */

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { clearBudget, listBudgets, setBudget, type UserBudget } from '@/api/budgets';
import { formatCents, formatTime } from '@/lib/format';

export default function BudgetLimits() {
  const [defaultCents, setDefaultCents] = useState(0);
  const [items, setItems] = useState<UserBudget[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [userId, setUserId] = useState('');
  const [cents, setCents] = useState('');

  useEffect(() => {
    let cancelled = false;
    const fetchBudgets = async () => {
      try {
        const data = await listBudgets();
        if (cancelled) return;
        setDefaultCents(data.default_cents);
        setItems(data.overrides);
        setError(null);
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : '预算配置加载失败（需要 admin 角色）');
        }
      }
    };
    void fetchBudgets();
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async () => {
    const id = userId.trim();
    const value = Number(cents);
    if (!id || !Number.isInteger(value) || value < 0) {
      setError('用户 id 不能为空，预算必须是 ≥ 0 的整数（单位：分）');
      return;
    }
    setSaving(true);
    try {
      const saved = await setBudget(id, value);
      // 服务端返回的就是库里的行（含 updated_at），按 user_id 插回有序位置，
      // 不用再拉一次；数组是新建的，不原地改 state
      setItems((current) => {
        const next = current.filter((item) => item.user_id !== saved.user_id);
        const at = next.findIndex((item) => item.user_id > saved.user_id);
        next.splice(at === -1 ? next.length : at, 0, saved);
        return next;
      });
      setUserId('');
      setCents('');
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '预算保存失败');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await clearBudget(id);
      setItems((current) => current.filter((item) => item.user_id !== id));
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '预算覆盖删除失败');
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          个人日预算
          <Badge variant="secondary">
            默认{defaultCents > 0 ? ` ${formatCents(defaultCents)}` : '不限'}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="text-[11px] text-muted-foreground">
            用户 id
            <Input
              value={userId}
              aria-label="用户 id"
              placeholder="u_102"
              className="mt-1 h-8 w-36 font-mono text-xs"
              onChange={(event) => setUserId(event.target.value)}
            />
          </div>
          <div className="text-[11px] text-muted-foreground">
            日上限（分）
            <Input
              value={cents}
              aria-label="日上限（分）"
              inputMode="numeric"
              placeholder="100"
              className="mt-1 h-8 w-28 font-mono text-xs"
              onChange={(event) => setCents(event.target.value)}
            />
          </div>
          <Button size="sm" className="h-8" disabled={saving} onClick={() => void save()}>
            保存
          </Button>
          {saving && <span className="text-xs text-muted-foreground">保存中…</span>}
        </div>

        {items.length === 0 ? (
          <p className="text-xs text-muted-foreground">还没有按用户的覆盖：所有用户都按默认值。</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>用户</TableHead>
                <TableHead className="text-right">日上限</TableHead>
                <TableHead>修改人</TableHead>
                <TableHead>修改时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.user_id}>
                  <TableCell className="font-mono text-xs">{item.user_id}</TableCell>
                  <TableCell className="text-right text-xs">
                    {item.daily_cents > 0 ? formatCents(item.daily_cents) : '不限'}
                  </TableCell>
                  <TableCell className="text-xs">{item.updated_by}</TableCell>
                  <TableCell className="text-xs">{formatTime(item.updated_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={() => void remove(item.user_id)}
                    >
                      撤销
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {error && <p className="text-xs text-danger">{error}</p>}

        <p className="text-[11px] text-muted-foreground">
          0 = 该用户不限（显式覆盖默认值）；删除覆盖才回到默认值。个人额度用完时在模型请求前拒绝，
          run 以 <code>BUDGET_EXCEEDED</code>{' '}
          失败、被拒的这次调用不产生费用；全局日预算仍然照常兜底。 保存后立即生效，多副本最多 2
          秒。只有真实模型调用会记账：mock 模式成本恒为 0。
        </p>
      </CardContent>
    </Card>
  );
}
