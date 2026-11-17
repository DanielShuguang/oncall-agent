import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
import type { SessionPinAction, SessionPinAudit } from '@/api/pinAudits';
import { formatTime } from '@/lib/format';

export type ActionFilter = 'all' | SessionPinAction;
export type PinAuditDraft = {
  userId: string;
  sessionId: string;
  action: ActionFilter;
  from: string;
  to: string;
};

export const ACTION_LABEL: Record<SessionPinAction, string> = {
  pin: '置顶',
  unpin: '取消置顶',
};

export function PinAuditFilterCard({
  draft,
  error,
  onChange,
  onApply,
  onClear,
}: {
  draft: PinAuditDraft;
  error: string | null;
  onChange: (patch: Partial<PinAuditDraft>) => void;
  onApply: () => void;
  onClear: () => void;
}) {
  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">用户</div>
            <Input
              aria-label="按用户筛选置顶审计"
              className="h-8 w-40 text-xs"
              placeholder="user_id"
              maxLength={64}
              value={draft.userId}
              onChange={(event) => onChange({ userId: event.target.value })}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">会话</div>
            <Input
              aria-label="按会话筛选置顶审计"
              className="h-8 w-48 text-xs"
              placeholder="session_id"
              maxLength={64}
              value={draft.sessionId}
              onChange={(event) => onChange({ sessionId: event.target.value })}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">动作</div>
            <Select
              value={draft.action}
              onValueChange={(next) => onChange({ action: next as ActionFilter })}
            >
              <SelectTrigger className="h-8 w-32 text-xs" aria-label="按动作筛选置顶审计">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部动作</SelectItem>
                <SelectItem value="pin">置顶</SelectItem>
                <SelectItem value="unpin">取消置顶</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">开始（UTC）</div>
            <Input
              aria-label="置顶审计开始日期"
              className="h-8 w-36 text-xs"
              type="date"
              value={draft.from}
              onChange={(event) => onChange({ from: event.target.value })}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">结束（UTC）</div>
            <Input
              aria-label="置顶审计结束日期"
              className="h-8 w-36 text-xs"
              type="date"
              value={draft.to}
              onChange={(event) => onChange({ to: event.target.value })}
            />
          </div>
          <Button size="sm" className="h-8 text-xs" onClick={onApply}>
            筛选
          </Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={onClear}>
            清除
          </Button>
        </div>
        {error && <p className="mt-2 text-[11px] text-danger">{error}</p>}
        <p className="mt-2 text-[11px] text-muted-foreground">
          用户与会话均为精确匹配；日期为 UTC 自然日闭区间，两端需同时填写且最多 365
          天；重置或续签不产生审计，审计只属于显式置顶/取消置顶。
        </p>
      </CardContent>
    </Card>
  );
}

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
