/** 个人日预算（ADR-0026/0028）：默认值 + 按用户覆盖，单位「分」，0 = 不限。 */

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
import {
  clearBudget,
  getBudgetUsage,
  listBudgets,
  setBudget,
  type BudgetUsage,
  type UserBudget,
} from '@/api/budgets';
import { formatCents, formatTime } from '@/lib/format';
import { mergeBudgetRows, type BudgetRow } from './budgetRows';

// 与后端 `app/schemas/budget.py` 的 MAX_DAILY_CENTS 一致（1 万元/天）
const MAX_DAILY_CENTS = 1_000_000;

type UsageState = 'loading' | 'ready' | 'error';

function limitLabel(cents: number | null): string {
  if (cents === null) return '—';
  return cents > 0 ? formatCents(cents) : '不限';
}

function spentLabel(row: BudgetRow, state: UsageState): string {
  if (row.spent_cents !== null) return formatCents(row.spent_cents);
  return state === 'loading' ? '…' : '—';
}

function remainingLabel(row: BudgetRow): string {
  if (row.daily_cents === null || row.daily_cents === 0 || row.spent_cents === null) return '—';
  return formatCents(Math.max(0, row.daily_cents - row.spent_cents));
}

export default function BudgetLimits() {
  const [defaultCents, setDefaultCents] = useState(0);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [items, setItems] = useState<UserBudget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [userId, setUserId] = useState('');
  const [cents, setCents] = useState('');

  const [usage, setUsage] = useState<BudgetUsage | null>(null);
  const [usageState, setUsageState] = useState<UsageState>('loading');
  const [usageError, setUsageError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchBudgets = async () => {
      try {
        const data = await listBudgets();
        if (cancelled) return;
        setDefaultCents(data.default_cents);
        setItems(data.overrides);
        setConfigLoaded(true);
        setError(null);
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : '预算配置加载失败（需要 admin 角色）');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    const fetchUsage = async () => {
      try {
        const data = await getBudgetUsage();
        if (cancelled) return;
        setUsage(data);
        setUsageState('ready');
        setUsageError(null);
      } catch (exc) {
        if (!cancelled) {
          setUsageState('error');
          setUsageError(exc instanceof Error ? exc.message : '今日用量加载失败');
        }
      }
    };
    void fetchBudgets();
    void fetchUsage();
    return () => {
      cancelled = true;
    };
  }, []);

  // usage 失败/未加载时传 null，表格显示「—」而不是 0；默认值未加载同理
  const usageUsers = usageState === 'ready' ? (usage?.users ?? []) : null;
  const rows = mergeBudgetRows(items, configLoaded ? defaultCents : null, usageUsers);
  // 空表可能是「没有覆盖」也可能是「用量没取到」，不能都说成「今天没有模型调用」
  const emptyHint =
    usageState === 'ready'
      ? '还没有覆盖，今天也还没有模型调用。'
      : usageState === 'loading'
        ? '还没有覆盖；今日用量加载中…'
        : '还没有覆盖；今日用量暂不可用。';

  const save = async () => {
    const id = userId.trim();
    const raw = cents.trim();
    const value = Number(raw);
    // 空串会被 Number('') 变成 0（= 不限），必须显式拦住：静默放开额度比报错危险
    if (!id || raw === '' || !Number.isInteger(value) || value < 0 || value > MAX_DAILY_CENTS) {
      setError(`用户 id 不能为空；预算必须是 0–${MAX_DAILY_CENTS} 的整数（单位：分）`);
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
            {loading
              ? '加载中…'
              : configLoaded
                ? `默认${defaultCents > 0 ? ` ${formatCents(defaultCents)}` : '不限'}`
                : '默认未知'}
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
          <Button
            size="sm"
            className="h-8"
            disabled={saving || loading}
            onClick={() => void save()}
          >
            保存
          </Button>
          {saving && <span className="text-xs text-muted-foreground">保存中…</span>}
        </div>

        {usageState === 'ready' && usage ? (
          <p className="text-[11px] text-muted-foreground">
            今日（UTC）：已用 {formatCents(usage.global_usage.spent_cents)}
            {usage.global_usage.limit_cents > 0
              ? ` / ${formatCents(usage.global_usage.limit_cents)}`
              : ' / 不限'}
            ；未结算预扣 {usage.global_usage.reservation_count} 笔（
            {formatCents(usage.global_usage.reserved_cents)}）
            {usage.global_usage.stale_count > 0 && (
              <span className="text-danger">
                ，其中 {usage.global_usage.stale_count} 笔超过{' '}
                {Math.round(usage.stale_after_s / 60)} 分钟
              </span>
            )}
          </p>
        ) : usageState === 'error' ? (
          <p className="text-[11px] text-danger">今日用量暂不可用：{usageError}</p>
        ) : (
          <p className="text-[11px] text-muted-foreground">今日用量加载中…</p>
        )}

        {loading ? (
          <p className="text-xs text-muted-foreground">加载中…</p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">{emptyHint}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>用户</TableHead>
                <TableHead className="text-right">今日已用</TableHead>
                <TableHead className="text-right">日上限</TableHead>
                <TableHead className="text-right">剩余</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>修改人</TableHead>
                <TableHead>修改时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.user_id}>
                  <TableCell className="font-mono text-xs">{row.user_id}</TableCell>
                  <TableCell className="text-right text-xs">
                    {spentLabel(row, usageState)}
                    {row.stale_count > 0 && (
                      <div className="text-[10px] text-danger">{row.stale_count} 笔预扣卡住</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right text-xs">
                    {limitLabel(row.daily_cents)}
                  </TableCell>
                  <TableCell className="text-right text-xs">{remainingLabel(row)}</TableCell>
                  <TableCell className="text-xs">
                    {row.source === 'override' ? (
                      <Badge variant="secondary">覆盖</Badge>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">默认</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">{row.updated_by ?? '—'}</TableCell>
                  <TableCell className="text-xs">
                    {row.updated_at ? formatTime(row.updated_at) : '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.source === 'override' ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        onClick={() => void remove(row.user_id)}
                      >
                        撤销
                      </Button>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">—</span>
                    )}
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
          秒。今日已用读账本，包含进行中的预扣，和上方按 <code>model_calls</code>{' '}
          聚合的成本可能不同；预扣超过 5 分钟未结算会标红，但不会自动回冲（账本按日过期自愈）。mock
          模式成本恒为 0。
        </p>
      </CardContent>
    </Card>
  );
}
