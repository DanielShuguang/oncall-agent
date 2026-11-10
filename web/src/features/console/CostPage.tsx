/** 成本看板（W4 D19）：按天 / 模型 / 用户聚合，数据源是 model_calls。 */

import { useEffect, useState } from 'react';
import { BarChart } from 'echarts/charts';
import { GridComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getCostSummary, type CostGroupBy, type CostSummary } from '@/api/cost';
import { formatCents } from '@/lib/format';
import BudgetLimits from './BudgetLimits';

const GROUP_OPTIONS: { value: CostGroupBy; label: string }[] = [
  { value: 'day', label: '按天' },
  { value: 'model', label: '按模型' },
  { value: 'user', label: '按用户' },
];

// 只注册成本页用到的图表与组件：整包 import 会让懒加载 chunk 超过 1 MB。
// 不用 TooltipComponent（会给每个柱子留 hover 值），精确值在下方表格可查。
echarts.use([BarChart, GridComponent, CanvasRenderer]);

function utcDay(offsetDays = 0): string {
  // API 的 from/to 是 UTC 自然日；用本地日期在 00:00–08:00 会偏一天（R6）
  return new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

function defaultRange(): { from: string; to: string } {
  return {
    from: utcDay(-6),
    to: utcDay(),
  };
}

/** ECharts 画在 canvas 上，读不到 CSS 变量，只能渲染前从设计令牌取一次值。 */
function tokenColor(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined;
}

export default function CostPage() {
  const [range, setRange] = useState(defaultRange);
  const [groupBy, setGroupBy] = useState<CostGroupBy>('day');
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchSummary = async () => {
      try {
        const data = await getCostSummary({ ...range, groupBy });
        if (cancelled) return;
        setSummary(data);
        setError(null);
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : '加载失败（需要 admin 角色）');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchSummary();
    return () => {
      cancelled = true;
    };
  }, [range, groupBy]);

  const items = summary?.items ?? [];
  const tokenTotal = items.reduce((sum, item) => sum + item.token_in + item.token_out, 0);
  const muted = tokenColor('--color-muted-fg');
  const line = tokenColor('--color-line');
  const brand = tokenColor('--color-brand');

  const option = {
    grid: { left: 48, right: 16, top: 24, bottom: 32 },
    xAxis: {
      type: 'category',
      data: items.map((item) => item.key),
      axisLabel: { fontSize: 11, color: muted },
    },
    yAxis: {
      type: 'value',
      name: '分',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLabel: { fontSize: 11, color: muted },
      splitLine: { lineStyle: { color: line } },
    },
    series: [
      {
        type: 'bar',
        data: items.map((item) => item.cost_cents),
        itemStyle: { color: brand, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 28,
        label: {
          show: items.length <= 12,
          position: 'top',
          fontSize: 10,
          color: muted,
        },
      },
    ],
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="text-xs text-muted-foreground">
          开始
          <Input
            type="date"
            aria-label="开始日期"
            value={range.from}
            className="mt-1 h-8 w-40 text-xs"
            onChange={(event) => {
              setLoading(true);
              setRange((current) => ({ ...current, from: event.target.value }));
            }}
          />
        </div>
        <div className="text-xs text-muted-foreground">
          结束
          <Input
            type="date"
            aria-label="结束日期"
            value={range.to}
            className="mt-1 h-8 w-40 text-xs"
            onChange={(event) => {
              setLoading(true);
              setRange((current) => ({ ...current, to: event.target.value }));
            }}
          />
        </div>
        <div className="text-xs text-muted-foreground">
          分组
          <Select
            value={groupBy}
            onValueChange={(value) => {
              setLoading(true);
              setGroupBy(value as CostGroupBy);
            }}
          >
            <SelectTrigger className="mt-1 h-8 w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {GROUP_OPTIONS.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={loading}
          onClick={() => {
            setLoading(true);
            // 新对象触发 effect 重跑；日期本身不变
            setRange((current) => ({ ...current }));
          }}
        >
          刷新
        </Button>
        {loading && <span className="text-xs text-muted-foreground">加载中…</span>}
      </div>

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{error}</CardContent>
        </Card>
      )}

      <div className="grid grid-cols-3 gap-3">
        <Stat label="总成本" value={formatCents(summary?.total_cents ?? 0)} />
        <Stat label="调用次数" value={`${summary?.calls ?? 0}`} />
        <Stat label="Token 总量" value={`${tokenTotal}`} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            成本分布
            <Badge variant="secondary">
              {GROUP_OPTIONS.find((o) => o.value === groupBy)?.label}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <div className="py-10 text-center text-xs text-muted-foreground">
              该时间段没有模型调用。mock 模式走规则节点，成本恒为 0。
            </div>
          ) : (
            <ReactEChartsCore echarts={echarts} option={option} className="h-64 w-full" notMerge />
          )}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  {groupBy === 'day' ? '日期' : groupBy === 'model' ? '模型' : '用户'}
                </TableHead>
                <TableHead className="text-right">调用</TableHead>
                <TableHead className="text-right">token in</TableHead>
                <TableHead className="text-right">token out</TableHead>
                <TableHead className="text-right">成本</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.key}>
                  <TableCell className="text-xs">{item.key}</TableCell>
                  <TableCell className="text-right text-xs">{item.calls}</TableCell>
                  <TableCell className="text-right text-xs">{item.token_in}</TableCell>
                  <TableCell className="text-right text-xs">{item.token_out}</TableCell>
                  <TableCell className="text-right text-xs">
                    {formatCents(item.cost_cents)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <BudgetLimits />

      <p className="text-[11px] text-muted-foreground">
        口径：聚合 <code>model_calls</code>，日期按 UTC 自然日，成本单位为分；与 run 详情里的
        token/cost 同源。真实成本需要配置 provider 单价（docs/02 §2.4）。
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-3">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <div className="mt-1 text-lg font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}
