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
import type { ApprovalDecision, ApprovalOut } from '@/api/approvals';
import { formatTime } from '@/lib/format';

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

interface Props {
  items: ApprovalOut[];
  status: string;
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  cursor: string | null;
  hasActiveFilters: boolean;
  onLoadMore: () => void;
  onResolve: (approval: ApprovalOut, decision: ApprovalDecision) => void;
}

export function ApprovalTableCard({
  items,
  status,
  total,
  loading,
  loadingMore,
  cursor,
  hasActiveFilters,
  onLoadMore,
  onResolve,
}: Props) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-0">
        {!loading && total !== null && total > 0 && (
          <div className="border-b px-3 py-2 text-[11px] text-muted-foreground">
            共 {total} 条{items.length < total ? `，已显示 ${items.length} 条` : ''}
          </div>
        )}
        {loading ? (
          <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-xs text-muted-foreground">
            {status === 'pending'
              ? '没有待办审批。'
              : hasActiveFilters
                ? '没有符合筛选条件的审批。'
                : '该状态下没有审批记录。'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>工具 / 参数</TableHead>
                  <TableHead>发起人</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>{status === 'pending' ? '过期时间' : '决议时间'}</TableHead>
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
                      {status === 'pending'
                        ? formatTime(item.expires_at)
                        : item.resolved_at
                          ? formatTime(item.resolved_at)
                          : '—'}
                    </TableCell>
                    <TableCell className="text-right align-top">
                      <div className="flex justify-end gap-1">
                        {item.status === 'pending' && (
                          <>
                            <Button
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => onResolve(item, 'approved')}
                            >
                              批准
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => onResolve(item, 'rejected')}
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
        {!loading && cursor && (
          <div className="border-t p-3 text-center">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={loadingMore}
              onClick={onLoadMore}
            >
              {loadingMore ? '加载中…' : '加载更多'}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
