/** 会话恢复审计（W6 后补）：管理端只读列表、过滤、翻页、首屏总数、统计与 CSV 导出（ADR-0063/0064/0065）。 */

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
  exportSessionRestoreAuditsCsv,
  getSessionRestoreAuditStats,
  listSessionRestoreAudits,
  type SessionRestoreAudit,
  type SessionRestoreAuditFilters,
  type SessionRestoreAuditStats,
} from '@/api/sessionAudits';
import { formatTime } from '@/lib/format';
import { downloadBlob } from '@/lib/download';

const PAGE_SIZE = 20;
const STATS_DAYS = [7, 30, 90] as const;

export default function AuditPage() {
  const [items, setItems] = useState<SessionRestoreAudit[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [statsDays, setStatsDays] = useState<number>(30);
  const [stats, setStats] = useState<SessionRestoreAuditStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [filters, setFilters] = useState<SessionRestoreAuditFilters>({});
  const [filterUserId, setFilterUserId] = useState('');
  const [filterSessionId, setFilterSessionId] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<{ text: string; failed: boolean } | null>(
    null,
  );
  const hasActiveFilters = Boolean(filters.userId || filters.sessionId);
  // 切过滤/重试后在途请求不能覆盖新列表；导出/统计同理。
  const listRequest = useRef(0);
  const exportRequest = useRef(0);
  const statsRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++listRequest.current;
    const load = async () => {
      setLoading(true);
      setItems([]);
      setTotal(null);
      setCursor(null);
      setError(null);
      setLoadingMore(false);
      try {
        const data = await listSessionRestoreAudits(filters, null, PAGE_SIZE);
        if (!cancelled && listRequest.current === requestId) {
          setItems(data.items);
          setCursor(data.next_cursor);
          setTotal(data.total ?? null);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled && listRequest.current === requestId) {
          setError(exc instanceof Error ? exc.message : '恢复审计加载失败');
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

  useEffect(() => {
    let cancelled = false;
    const requestId = ++statsRequest.current;
    const load = async () => {
      setStatsLoading(true);
      setStatsError(null);
      try {
        const data = await getSessionRestoreAuditStats(statsDays);
        if (!cancelled && statsRequest.current === requestId) setStats(data);
      } catch (exc) {
        if (!cancelled && statsRequest.current === requestId) {
          setStatsError(exc instanceof Error ? exc.message : '统计加载失败');
        }
      } finally {
        if (!cancelled && statsRequest.current === requestId) setStatsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
      statsRequest.current += 1;
    };
  }, [statsDays]);

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    const requestId = listRequest.current;
    setLoadingMore(true);
    try {
      const data = await listSessionRestoreAudits(filters, cursor, PAGE_SIZE);
      if (listRequest.current !== requestId) return;
      setItems((current) => [...current, ...data.items]);
      setCursor(data.next_cursor);
      setError(null);
    } catch (exc) {
      if (listRequest.current === requestId) {
        setError(exc instanceof Error ? exc.message : '加载更多恢复审计失败');
      }
    } finally {
      if (listRequest.current === requestId) setLoadingMore(false);
    }
  };

  const exportCsv = async () => {
    if (exporting) return;
    const requestId = ++exportRequest.current;
    setExporting(true);
    setExportMessage(null);
    try {
      const result = await exportSessionRestoreAuditsCsv(filters);
      if (exportRequest.current !== requestId) return;
      downloadBlob(result.blob, 'session-restores.csv');
      setExportMessage({
        failed: false,
        text: result.truncated
          ? `已导出前 ${result.count} 条；超过 5000 条上限，已截断。`
          : `已导出 ${result.count} 条恢复审计。`,
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

  const resetForFilters = () => {
    // 立即失效旧列表/旧导出，避免 setFilters 生效前的一帧里旧行显示在新过滤条件下。
    listRequest.current += 1;
    setItems([]);
    setTotal(null);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    exportRequest.current += 1;
    setExporting(false);
    setExportMessage(null);
  };

  const applyFilters = () => {
    resetForFilters();
    const userId = filterUserId.trim();
    const sessionId = filterSessionId.trim();
    setFilters({
      ...(userId ? { userId } : {}),
      ...(sessionId ? { sessionId } : {}),
    });
  };

  const clearFilters = () => {
    resetForFilters();
    setFilterUserId('');
    setFilterSessionId('');
    setFilters({});
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-xs text-muted-foreground">
          管理员只读：每次恢复操作一行，只记录真正恢复的会话；审计独立保留 365 天。
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
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-xs font-medium">恢复活动 · 全部用户</div>
            <div className="ml-auto flex items-center gap-1">
              {STATS_DAYS.map((days) => (
                <Button
                  key={days}
                  variant={statsDays === days ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2 text-xs"
                  aria-pressed={statsDays === days}
                  onClick={() => setStatsDays(days)}
                >
                  近 {days} 天
                </Button>
              ))}
            </div>
          </div>
          {statsLoading ? (
            <p className="text-xs text-muted-foreground">统计加载中…</p>
          ) : statsError ? (
            <p className="text-xs text-danger">统计暂不可用：{statsError}</p>
          ) : stats ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <div className="text-[11px] text-muted-foreground">恢复操作</div>
                <div className="text-lg font-semibold text-foreground">{stats.restores}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">涉及用户</div>
                <div className="text-lg font-semibold text-foreground">{stats.users}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">恢复会话</div>
                <div className="text-lg font-semibold text-foreground">{stats.sessions}</div>
              </div>
            </div>
          ) : null}
          {stats && !statsLoading && !statsError ? (
            <p className="text-[11px] text-muted-foreground">
              UTC 日期；{stats.daily.length} 个日期有恢复记录。统计不随下方用户/会话过滤变化。
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card className="py-0">
        <CardContent className="p-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <div className="text-[11px] text-muted-foreground">用户</div>
              <Input
                aria-label="按用户筛选恢复审计"
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
                aria-label="按会话筛选恢复审计"
                className="h-8 w-48 text-xs"
                placeholder="session_id"
                maxLength={64}
                value={filterSessionId}
                onChange={(event) => setFilterSessionId(event.target.value)}
              />
            </div>
            <Button size="sm" className="h-8 text-xs" onClick={applyFilters}>
              筛选
            </Button>
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
              清除
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            用户与会话均为精确匹配；session_id 走 JSONB 包含查询，可定位「这个会话被谁恢复过」。
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
                        <div className="flex max-h-28 max-w-[32rem] flex-wrap gap-1 overflow-auto">
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
