/** 运行列表（W4 D19）：自己发起的 run，按开始时间倒序分页。 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
import { listRuns, type RunSummary } from '@/api/runs';
import { failureLabel, formatCents, formatTime, STATUS_TONES, statusLabel } from '@/lib/format';

const STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'awaiting_approval', label: '待审批' },
  { value: 'running', label: '执行中' },
  { value: 'interrupted', label: '已中断' },
];

export default function RunsPage() {
  const [items, setItems] = useState<RunSummary[]>([]);
  const [status, setStatus] = useState('all');
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchFirstPage = async () => {
      try {
        const res = await listRuns({
          limit: 20,
          status: status === 'all' ? null : status,
        });
        if (cancelled) return;
        setItems(res.items);
        setCursor(res.next_cursor);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchFirstPage();
    return () => {
      cancelled = true;
    };
  }, [status]);

  const onStatusChange = (next: string) => {
    setLoading(true);
    setError(null);
    setStatus(next);
  };

  const loadMore = async () => {
    if (!cursor) return;
    setLoading(true);
    try {
      const res = await listRuns({
        limit: 20,
        cursor,
        status: status === 'all' ? null : status,
      });
      setItems((current) => [...current, ...res.items]);
      setCursor(res.next_cursor);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">运行记录</h2>
          <p className="mt-1 mb-0 text-xs text-muted-foreground">
            事件是唯一真相源；点进任意 run 可按 seq 回放完整过程与模型成本。
          </p>
        </div>
        <Select value={status} onValueChange={onStatusChange}>
          <SelectTrigger className="h-8 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error && (
        <Card className="mb-3 border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{error}</CardContent>
        </Card>
      )}

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>模型</TableHead>
                <TableHead className="text-right">步数</TableHead>
                <TableHead className="text-right">Token</TableHead>
                <TableHead className="text-right">成本</TableHead>
                <TableHead>开始时间</TableHead>
                <TableHead>归因</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.run_id}>
                  <TableCell>
                    <Link
                      to={`/runs/${item.run_id}`}
                      className="font-mono text-xs text-brand hover:underline"
                    >
                      {item.run_id.slice(0, 8)}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={STATUS_TONES[item.status]}>
                      {statusLabel(item.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{item.model ?? '-'}</TableCell>
                  <TableCell className="text-right text-xs">
                    {item.step_count}/{item.max_steps}
                  </TableCell>
                  <TableCell className="text-right text-xs">
                    {item.token_in + item.token_out}
                  </TableCell>
                  <TableCell className="text-right text-xs">
                    {formatCents(item.cost_cents)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatTime(item.started_at)}
                  </TableCell>
                  <TableCell className="text-xs">
                    {item.status === 'failed' ? failureLabel(item.failure_category) : '-'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {!loading && items.length === 0 && (
            <div className="p-8 text-center text-sm text-muted-foreground">
              还没有运行记录。回对话页问一个问题就会生成。
            </div>
          )}
          {loading && <div className="p-4 text-center text-xs text-muted-foreground">加载中…</div>}
        </CardContent>
      </Card>

      {cursor && (
        <div className="mt-3 flex justify-center">
          <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadMore()}>
            加载更多
          </Button>
        </div>
      )}
    </div>
  );
}
