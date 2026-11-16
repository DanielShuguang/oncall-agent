/** 置顶/取消置顶审计（W6 后补）：管理员只读列表、过滤、游标翻页与 CSV 导出（ADR-0085）。 */

import { useEffect, useRef, useState } from 'react';
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
import {
  exportSessionPinAuditsCsv,
  listSessionPinAudits,
  type SessionPinAction,
  type SessionPinAudit,
  type SessionPinAuditFilters,
} from '@/api/pinAudits';
import { downloadBlob } from '@/lib/download';
import { formatTime } from '@/lib/format';

const PAGE_SIZE = 20;

type ActionFilter = 'all' | SessionPinAction;

const ACTION_LABEL: Record<SessionPinAction, string> = {
  pin: '置顶',
  unpin: '取消置顶',
};

export default function PinAuditPage() {
  const [filters, setFilters] = useState<SessionPinAuditFilters>({});
  const [filterUserId, setFilterUserId] = useState('');
  const [filterSessionId, setFilterSessionId] = useState('');
  const [filterAction, setFilterAction] = useState<ActionFilter>('all');
  const [items, setItems] = useState<SessionPinAudit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<{ text: string; failed: boolean } | null>(
    null,
  );
  const hasActiveFilters = Boolean(filters.userId || filters.sessionId || filters.action);
  // 切换过滤后，旧列表/旧导出都不能再覆盖新结果。
  const listRequest = useRef(0);
  const exportRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++listRequest.current;
    const load = async () => {
      setLoading(true);
      setItems([]);
      setCursor(null);
      setError(null);
      setLoadingMore(false);
      setExportMessage(null);
      try {
        const data = await listSessionPinAudits(filters, null, PAGE_SIZE);
        if (!cancelled && listRequest.current === requestId) {
          setItems(data.items);
          setCursor(data.next_cursor);
        }
      } catch (exc) {
        if (!cancelled && listRequest.current === requestId) {
          setError(exc instanceof Error ? exc.message : '置顶审计加载失败');
        }
      } finally {
        if (!cancelled && listRequest.current === requestId) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
      listRequest.current += 1;
    };
  }, [filters]);

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = listRequest.current;
    setLoadingMore(true);
    try {
      const data = await listSessionPinAudits(filters, cursor, PAGE_SIZE);
      if (listRequest.current !== requestId) return;
      setItems((current) => [...current, ...data.items]);
      setCursor(data.next_cursor);
      setError(null);
    } catch (exc) {
      if (listRequest.current === requestId) {
        setError(exc instanceof Error ? exc.message : '加载更多置顶审计失败');
      }
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const applyFilters = () => {
    const userId = filterUserId.trim();
    const sessionId = filterSessionId.trim();
    // 立即清空旧行，避免 setFilters 生效前的一帧仍显示旧过滤结果。
    listRequest.current += 1;
    setItems([]);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setExportMessage(null);
    exportRequest.current += 1;
    setExporting(false);
    setFilters({
      ...(userId ? { userId } : {}),
      ...(sessionId ? { sessionId } : {}),
      ...(filterAction === 'all' ? {} : { action: filterAction }),
    });
  };

  const clearFilters = () => {
    setFilterUserId('');
    setFilterSessionId('');
    setFilterAction('all');
    listRequest.current += 1;
    setItems([]);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setExportMessage(null);
    exportRequest.current += 1;
    setExporting(false);
    setFilters({});
  };

  const exportCsv = async () => {
    if (exporting) return;
    const requestId = ++exportRequest.current;
    setExporting(true);
    setExportMessage(null);
    try {
      const result = await exportSessionPinAuditsCsv(filters);
      if (exportRequest.current !== requestId) return;
      downloadBlob(result.blob, 'session-pins.csv');
      setExportMessage({
        failed: false,
        text: result.truncated
          ? `已导出前 ${result.count} 条；超过 5000 条上限，已截断。`
          : `已导出 ${result.count} 条置顶审计。`,
      });
    } catch (exc) {
      if (exportRequest.current !== requestId) return;
      setExportMessage({
        failed: true,
        text: exc instanceof Error ? exc.message : '导出失败',
      });
    } finally {
      if (exportRequest.current === requestId) setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          管理员只读：只记录显式置顶/取消置顶；隐藏会话导致置顶清理不写审计。审计独立保留 365 天，
          导出是同步快照，最多 5000 条。
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={exporting}
          onClick={() => void exportCsv()}
        >
          {exporting ? '导出中…' : '导出 CSV'}
        </Button>
      </div>

      {exportMessage && (
        <p className={exportMessage.failed ? 'text-xs text-danger' : 'text-xs text-ok'}>
          {exportMessage.text}
        </p>
      )}

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
                value={filterUserId}
                onChange={(event) => setFilterUserId(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <div className="text-[11px] text-muted-foreground">会话</div>
              <Input
                aria-label="按会话筛选置顶审计"
                className="h-8 w-48 text-xs"
                placeholder="session_id"
                maxLength={64}
                value={filterSessionId}
                onChange={(event) => setFilterSessionId(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <div className="text-[11px] text-muted-foreground">动作</div>
              <Select
                value={filterAction}
                onValueChange={(next) => setFilterAction(next as ActionFilter)}
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
            <Button size="sm" className="h-8 text-xs" onClick={applyFilters}>
              筛选
            </Button>
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
              清除
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            用户与会话均为精确匹配；重置或续签不产生审计，审计只属于显式置顶/取消置顶。
          </p>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="flex flex-wrap items-center gap-3 p-3 text-xs text-danger">
            <span className="min-w-0 flex-1">{error}</span>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setFilters((current) => ({ ...current }))}
            >
              重试
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="gap-0 py-0">
        <CardContent className="p-0">
          {!loading && items.length > 0 && (
            <div className="border-b px-3 py-2 text-[11px] text-muted-foreground">
              已加载 {items.length} 条{hasActiveFilters ? '（当前筛选）' : ''}
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
                      <TableCell className="align-top font-mono text-xs">
                        {item.session_id}
                      </TableCell>
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
                onClick={() => void loadMore()}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
