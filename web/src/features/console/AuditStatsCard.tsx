/** 恢复审计顶部统计卡（ADR-0065/0066/0067/0070）。 */

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { SessionRestoreAuditFilters, SessionRestoreAuditStats } from '@/api/sessionAudits';
import { AUDIT_STATS_DAYS, type AuditStatsDays } from './auditFilterMemory';

interface AuditStatsCardProps {
  stats: SessionRestoreAuditStats | null;
  loading: boolean;
  error: string | null;
  days: AuditStatsDays;
  hasDateRange: boolean;
  filters: SessionRestoreAuditFilters;
  exporting: boolean;
  message: { text: string; failed: boolean } | null;
  onChangeDays: (days: AuditStatsDays) => void;
  onExport: () => void;
}

export function AuditStatsCard({
  stats,
  loading,
  error,
  days,
  hasDateRange,
  filters,
  exporting,
  message,
  onChangeDays,
  onExport,
}: AuditStatsCardProps) {
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-xs font-medium">
            {filters.userId || filters.sessionId || hasDateRange
              ? '恢复活动 · 当前过滤'
              : '恢复活动 · 全部用户'}
          </div>
          <div className="ml-auto flex items-center gap-1">
            {hasDateRange ? (
              <span className="text-[11px] text-muted-foreground">
                {filters.restoredFrom} ~ {filters.restoredTo}
              </span>
            ) : (
              AUDIT_STATS_DAYS.map((value) => (
                <Button
                  key={value}
                  variant={days === value ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2 text-xs"
                  aria-pressed={days === value}
                  onClick={() => onChangeDays(value)}
                >
                  近 {value} 天
                </Button>
              ))
            )}
            {stats && !loading && !error && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={exporting}
                onClick={onExport}
              >
                {exporting ? '导出中…' : '导出统计'}
              </Button>
            )}
          </div>
        </div>
        {loading ? (
          <p className="text-xs text-muted-foreground">统计加载中…</p>
        ) : error ? (
          <p className="text-xs text-danger">统计暂不可用：{error}</p>
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
        {stats && !loading && !error ? (
          <p className="text-[11px] text-muted-foreground">
            UTC 日期；{stats.daily.length} 个日期有恢复记录。统计跟随下方已应用的过滤。
          </p>
        ) : null}
        {message ? (
          <p className={message.failed ? 'text-xs text-danger' : 'text-xs text-ok'}>
            {message.text}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
