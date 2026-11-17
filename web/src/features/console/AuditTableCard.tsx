/** 恢复审计结果表与加载更多（ADR-0063/0064/0067）。 */

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
import type { SessionRestoreAudit } from '@/api/sessionAudits';
import { formatTime } from '@/lib/format';

interface AuditTableCardProps {
  items: SessionRestoreAudit[];
  total: number | null;
  hasActiveFilters: boolean;
  loading: boolean;
  loadingMore: boolean;
  cursor: string | null;
  error: string | null;
  onRetry: () => void;
  onLoadMore: () => void;
}

export function AuditTableCard({
  items,
  total,
  hasActiveFilters,
  loading,
  loadingMore,
  cursor,
  error,
  onRetry,
  onLoadMore,
}: AuditTableCardProps) {
  return (
    <>
      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="flex flex-wrap items-center gap-3 p-3 text-xs text-danger">
            <span className="min-w-0 flex-1">{error}</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onRetry}>
              重试
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          {!loading && items.length > 0 && (
            <div className="border-b px-3 py-2 text-[11px] text-muted-foreground">
              {total !== null && total > 0
                ? `共 ${total} 条${hasActiveFilters ? '（当前筛选）' : ''}${
                    items.length < total ? `，已加载 ${items.length} 条` : ''
                  }`
                : `已加载 ${items.length} 条${hasActiveFilters ? '（当前筛选）' : ''}`}
            </div>
          )}
          {loading ? (
            <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
          ) : items.length === 0 ? (
            <div className="p-8 text-center text-xs text-muted-foreground">
              {hasActiveFilters ? '没有符合筛选条件的恢复审计。' : '还没有恢复审计记录。'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>恢复时间</TableHead>
                    <TableHead>用户</TableHead>
                    <TableHead>请求 / 实际</TableHead>
                    <TableHead>恢复的会话</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="align-top text-xs whitespace-nowrap text-muted-foreground">
                        {formatTime(item.restored_at)}
                      </TableCell>
                      <TableCell className="align-top font-mono text-xs">{item.user_id}</TableCell>
                      <TableCell className="align-top text-xs whitespace-nowrap">
                        {item.requested_count} / {item.restored_count}
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="flex max-h-28 max-w-lg flex-wrap gap-1 overflow-auto">
                          {item.session_ids.map((sessionId) => (
                            <code
                              key={sessionId}
                              className="rounded border bg-canvas/50 px-1 py-0.5 font-mono text-[11px] break-all"
                            >
                              {sessionId}
                            </code>
                          ))}
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
                className="h-8 text-xs"
                disabled={loadingMore}
                onClick={onLoadMore}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}
