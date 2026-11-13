/** 审批中心（W5 D23）：待办 / 已办可筛，审批人才能决议。 */

import { useEffect, useRef, useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import {
  getApprovalStats,
  listApprovals,
  resolveApproval,
  type ApprovalDecision,
  type ApprovalOut,
  type ApprovalScope,
  type ApprovalStats,
} from '@/api/approvals';
import { formatDurationMs, formatTime } from '@/lib/format';

const STATS_DAYS = [7, 30, 90] as const;

type StatsGroup = 'none' | 'tool' | 'approver';

const STATUS_OPTIONS = [
  { value: 'pending', label: '待办' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'expired', label: '已过期' },
];

const STATUS_TONES: Record<string, string> = {
  pending: 'border-warn/20 bg-warn/10 text-warn',
  approved: 'border-ok/20 bg-ok/10 text-ok',
  rejected: 'border-danger/20 bg-danger/10 text-danger',
  expired: 'border-line bg-muted text-muted-foreground',
};

interface ResolveState {
  approval: ApprovalOut;
  decision: ApprovalDecision;
  reason: string;
  scope: ApprovalScope;
  submitting: boolean;
  error: string | null;
}

export default function ApprovalsPage() {
  const [status, setStatus] = useState('pending');
  const [items, setItems] = useState<ApprovalOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resolver, setResolver] = useState<ResolveState | null>(null);
  const [stats, setStats] = useState<ApprovalStats | null>(null);
  const [statsDays, setStatsDays] = useState(7);
  const [statsGroup, setStatsGroup] = useState<StatsGroup>('none');
  // 初始加载与决议后刷新可能并发，旧响应不能覆盖新统计（同会话列表的做法）。
  const statsRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    void getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup)
      .then((data) => {
        if (!cancelled && statsRequest.current === requestId) setStats(data);
        return data;
      })
      .catch(() => {
        if (!cancelled && statsRequest.current === requestId) setStats(null);
      });
    return () => {
      cancelled = true;
      statsRequest.current += 1;
    };
  }, [statsDays, statsGroup]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const data = await listApprovals(status);
        if (!cancelled) {
          setItems(data.items);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '审批列表加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [status]);

  const refresh = async () => {
    const data = await listApprovals(status);
    setItems(data.items);
  };

  const openResolve = (approval: ApprovalOut, decision: ApprovalDecision) => {
    setResolver({ approval, decision, reason: '', scope: 'once', submitting: false, error: null });
  };

  const submit = async () => {
    if (!resolver) return;
    setResolver({ ...resolver, submitting: true, error: null });
    try {
      const result = await resolveApproval(resolver.approval.approval_id, resolver.decision, {
        reason: resolver.reason.trim() || undefined,
        scope: resolver.decision === 'approved' ? resolver.scope : 'once',
      });
      setResolver(null);
      setNotice(
        `${resolver.decision === 'approved' ? '已批准' : '已拒绝'} ${
          resolver.approval.tool
        }；run 当前状态：${result.run_status ?? '未知'}。`,
      );
      try {
        await refresh();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : '决议已提交，但列表刷新失败');
      }
      const requestId = ++statsRequest.current;
      void getApprovalStats(statsDays, statsGroup === 'none' ? null : statsGroup)
        .then((data) => {
          if (statsRequest.current === requestId) setStats(data);
          return data;
        })
        .catch(() => {
          if (statsRequest.current === requestId) setStats(null);
        });
    } catch (exc) {
      setResolver((current) =>
        current
          ? {
              ...current,
              submitting: false,
              error: exc instanceof Error ? exc.message : '提交失败',
            }
          : current,
      );
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          审批人看到全部待办，普通员工只看到自己发起的；通过后从快照恢复 <code>act</code>，
          拒绝后不执行写工具。
        </div>
        <fieldset className="flex items-center gap-1">
          <legend className="sr-only">统计时间窗口</legend>
          {STATS_DAYS.map((days) => (
            <Button
              key={days}
              size="sm"
              variant={statsDays === days ? 'secondary' : 'ghost'}
              aria-pressed={statsDays === days}
              onClick={() => setStatsDays(days)}
            >
              {days} 天
            </Button>
          ))}
        </fieldset>
        <Select value={statsGroup} onValueChange={(next) => setStatsGroup(next as StatsGroup)}>
          <SelectTrigger className="h-8 w-32 text-xs" aria-label="分组维度">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">不分组</SelectItem>
            <SelectItem value="tool">按工具</SelectItem>
            <SelectItem value="approver">按审批人</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={status}
          onValueChange={(next) => {
            setStatus(next);
            setNotice(null);
          }}
        >
          <SelectTrigger className="h-8 w-28 text-xs">
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

      {stats && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="py-0">
            <CardContent className="p-3">
              <div className="text-[11px] text-muted-foreground">待审批</div>
              <div className="mt-1 text-lg font-medium">{stats.pending_count}</div>
              <div className="text-[11px] text-muted-foreground">
                {stats.oldest_pending_age_s === null
                  ? '没有积压'
                  : `最久已等 ${formatDurationMs(stats.oldest_pending_age_s * 1000)}`}
              </div>
            </CardContent>
          </Card>
          <Card className="py-0">
            <CardContent className="p-3">
              <div className="text-[11px] text-muted-foreground">近 {stats.days} 天已决议</div>
              <div className="mt-1 text-lg font-medium">{stats.decided_count}</div>
              <div className="text-[11px] text-muted-foreground">不含过期</div>
            </CardContent>
          </Card>
          <Card className="py-0">
            <CardContent className="p-3">
              <div className="text-[11px] text-muted-foreground">平均等待</div>
              <div className="mt-1 text-lg font-medium">
                {stats.avg_wait_ms === null ? '—' : formatDurationMs(stats.avg_wait_ms)}
              </div>
              <div className="text-[11px] text-muted-foreground">发起 → 决议</div>
            </CardContent>
          </Card>
          <Card className="py-0">
            <CardContent className="p-3">
              <div className="text-[11px] text-muted-foreground">最长等待</div>
              <div className="mt-1 text-lg font-medium">
                {stats.max_wait_ms === null ? '—' : formatDurationMs(stats.max_wait_ms)}
              </div>
              <div className="text-[11px] text-muted-foreground">窗口内已决议</div>
            </CardContent>
          </Card>
        </div>
      )}

      {stats && (
        <Card className="py-0">
          <CardContent className="p-3">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-xs font-medium">按日决议</div>
              <div className="text-[11px] text-muted-foreground">
                近 {stats.days} 天 · UTC · 只列有决议的日期
              </div>
            </div>
            {stats.daily.length === 0 ? (
              <p className="text-xs text-muted-foreground">窗口内还没有已决议的审批。</p>
            ) : (
              <div className="space-y-1">
                {stats.daily.map((day) => (
                  <div
                    key={day.day}
                    className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs"
                  >
                    <span className="w-12 shrink-0 text-muted-foreground">{day.day.slice(5)}</span>
                    <span>{day.decided_count} 单</span>
                    <span className="text-muted-foreground">
                      {day.avg_wait_ms === null
                        ? '平均等待 —'
                        : `平均等待 ${formatDurationMs(day.avg_wait_ms)}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {stats && statsGroup !== 'none' && (
        <Card className="py-0">
          <CardContent className="p-3">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-xs font-medium">分组统计</div>
              <div className="text-[11px] text-muted-foreground">
                近 {stats.days} 天 · 按{statsGroup === 'tool' ? '工具' : '审批人'} · 只含已决议
              </div>
            </div>
            {stats.groups.length === 0 ? (
              <p className="text-xs text-muted-foreground">窗口内还没有已决议的审批。</p>
            ) : (
              <div className="space-y-1">
                {stats.groups.map((group) => (
                  <div
                    key={group.key}
                    className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs"
                  >
                    <span className="min-w-28 shrink-0 font-mono text-muted-foreground">
                      {group.key}
                    </span>
                    <span>{group.decided_count} 单</span>
                    <span className="text-muted-foreground">
                      平均 {group.avg_wait_ms === null ? '—' : formatDurationMs(group.avg_wait_ms)}
                    </span>
                    <span className="text-muted-foreground">
                      最长 {group.max_wait_ms === null ? '—' : formatDurationMs(group.max_wait_ms)}
                    </span>
                  </div>
                ))}
                {stats.groups_truncated && (
                  <p className="text-[11px] text-muted-foreground">分组过多，只显示前 20 组。</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

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
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-xs text-muted-foreground">
              {status === 'pending' ? '没有待办审批。' : '该状态下没有审批记录。'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>工具 / 参数</TableHead>
                    <TableHead>发起人</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>过期时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.approval_id}>
                      <TableCell className="max-w-96 align-top">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline">{item.tool}</Badge>
                          <Badge variant="secondary" className="text-[10px]">
                            {item.risk_level}
                          </Badge>
                        </div>
                        <pre className="mt-2 max-h-28 overflow-auto rounded-md border bg-canvas/50 p-2 font-mono text-[11px] whitespace-pre-wrap">
                          {JSON.stringify(item.args, null, 2)}
                        </pre>
                        {item.reason && (
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            理由：{item.reason}
                          </div>
                        )}
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                          run {item.run_id}
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-xs">
                        {item.requested_by}
                        {item.resolved_by && (
                          <div className="text-[11px] text-muted-foreground">
                            处理人 {item.resolved_by}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge
                          variant="outline"
                          className={STATUS_TONES[item.status] ?? 'text-muted-foreground'}
                        >
                          {STATUS_OPTIONS.find((option) => option.value === item.status)?.label ??
                            item.status}
                        </Badge>
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {formatTime(item.created_at)}
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-xs text-muted-foreground">
                        {formatTime(item.expires_at)}
                      </TableCell>
                      <TableCell className="text-right align-top">
                        <div className="flex justify-end gap-1">
                          {item.status === 'pending' && (
                            <>
                              <Button
                                size="sm"
                                className="h-7 text-xs"
                                onClick={() => openResolve(item, 'approved')}
                              >
                                批准
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 text-xs"
                                onClick={() => openResolve(item, 'rejected')}
                              >
                                拒绝
                              </Button>
                            </>
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
        只有 <code>ONCALL_APPROVER_ROLES</code> 中的角色能决议，且不能审批自己发起的操作；
        <code>scope=session</code> 授权按「用户 + 会话 + 工具」隔离，默认 8 小时过期。
        运行详情目前只对发起人开放，审批人凭参数快照决议；跨用户读 run 需要单独授权。
      </p>

      <Dialog
        open={resolver !== null}
        onOpenChange={(open) => {
          if (!open && !resolver?.submitting) setResolver(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {resolver?.decision === 'approved' ? '批准' : '拒绝'} {resolver?.approval.tool}
            </DialogTitle>
            <DialogDescription>
              发起人 {resolver?.approval.requested_by}；审批后 run 会继续执行或转人工。
            </DialogDescription>
          </DialogHeader>

          <pre className="max-h-48 overflow-auto rounded-md border bg-panel p-3 font-mono text-xs whitespace-pre-wrap">
            {JSON.stringify(resolver?.approval.args ?? {}, null, 2)}
          </pre>

          {resolver?.decision === 'approved' && (
            <div className="text-xs text-muted-foreground">
              授权范围
              <Select
                value={resolver.scope}
                onValueChange={(next) =>
                  setResolver((current) =>
                    current ? { ...current, scope: next as ApprovalScope } : current,
                  )
                }
              >
                <SelectTrigger className="mt-1 h-8 w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="once">仅本次</SelectItem>
                  <SelectItem value="session">本会话同类工具（8 小时）</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <div>
            <div className="mb-1 text-xs text-muted-foreground">理由（可选）</div>
            <Textarea
              rows={3}
              aria-label="审批理由"
              placeholder={resolver?.decision === 'rejected' ? '建议填写拒绝原因' : '可留空'}
              className="text-xs"
              value={resolver?.reason ?? ''}
              disabled={resolver?.submitting}
              onChange={(event) =>
                setResolver((current) =>
                  current ? { ...current, reason: event.target.value } : current,
                )
              }
            />
          </div>

          {resolver?.error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {resolver.error}
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              disabled={resolver?.submitting}
              onClick={() => setResolver(null)}
            >
              取消
            </Button>
            <Button
              variant={resolver?.decision === 'rejected' ? 'destructive' : 'default'}
              disabled={resolver?.submitting}
              onClick={() => void submit()}
            >
              {resolver?.submitting ? '提交中…' : '确认提交'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
