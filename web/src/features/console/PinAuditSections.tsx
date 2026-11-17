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
import type { SessionPinAction, SessionPinAudit } from '@/api/pinAudits';
import { formatTime } from '@/lib/format';

export const ACTION_LABEL: Record<SessionPinAction, string> = {
  pin: '置顶',
  unpin: '取消置顶',
};

export function PinAuditListCard({
  items,
  total,
  cursor,
  loading,
  loadingMore,
  error,
  hasActiveFilters,
  onLoadMore,
}: {
  items: SessionPinAudit[];
  total: number | null;
  cursor: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  hasActiveFilters: boolean;
  onLoadMore: () => void;
}) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-0">
        {!loading && items.length > 0 && (
          <div className="border-b px-3 py-2 text-[11px] text-muted-foreground">
            {total !== null
              ? `共 ${total} 条 · 已加载 ${items.length} 条`
              : `已加载 ${items.length} 条`}
            {hasActiveFilters ? '（当前筛选）' : ''}
          </div>
        )}
        {loading ? (
          <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
        ) : error ? null : items.length === 0 ? (
          <div className="p-8 text-center text-xs text-muted-foreground">
            {hasActiveFilters ? '没有符合筛选条件的置顶审计。' : '还没有置顶审计记录。'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>会话</TableHead>
                  <TableHead>动作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="align-top text-xs whitespace-nowrap text-muted-foreground">
                      {formatTime(item.created_at)}
                    </TableCell>
                    <TableCell className="align-top font-mono text-xs">{item.user_id}</TableCell>
                    <TableCell className="align-top font-mono text-xs">{item.session_id}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={item.action === 'pin' ? 'secondary' : 'outline'}>
                        {ACTION_LABEL[item.action]}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {!loading && cursor && (
          <div className="flex items-center justify-between border-t px-3 py-2">
            <span className="text-[11px] text-muted-foreground">继续加载更早的记录</span>
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
