import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ApprovalStats } from '@/api/approvals';
import { formatDurationMs } from '@/lib/format';
import { APPROVAL_STATS_REFRESH_MS, formatStatsUpdatedAt } from './approvalStatsRefresh';
import type { StatsGroup } from './approvalTypes';

const STATS_DAYS = [7, 30, 90] as const;

function formatHourRange(hour: number): string {
  const label = String(hour).padStart(2, '0');
  return `${label}:00–${label}:59`;
}

interface Props {
  stats: ApprovalStats | null;
  statsDays: number;
  statsGroup: StatsGroup;
  statsGroupView: StatsGroup;
  statsExporting: boolean;
  statsExportMessage: { text: string; failed: boolean } | null;
  lastUpdatedAt: number | null;
  refreshing: boolean;
  onChangeDays: (days: number) => void;
  onChangeGroup: (group: StatsGroup) => void;
  onExport: () => void;
  onRefresh: () => void;
}

export function ApprovalStatsPanel({
  stats,
  statsDays,
  statsGroup,
  statsGroupView,
  statsExporting,
  statsExportMessage,
  lastUpdatedAt,
  refreshing,
  onChangeDays,
  onChangeGroup,
  onExport,
  onRefresh,
}: Props) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <fieldset className="flex items-center gap-1">
          <legend className="sr-only">统计时间窗口</legend>
          {STATS_DAYS.map((days) => (
            <Button
              key={days}
              size="sm"
              variant={statsDays === days ? 'secondary' : 'ghost'}
              aria-pressed={statsDays === days}
              onClick={() => onChangeDays(days)}
            >
              {days} 天
            </Button>
          ))}
        </fieldset>
        <Select value={statsGroup} onValueChange={(next) => onChangeGroup(next as StatsGroup)}>
          <SelectTrigger className="h-8 w-32 text-xs" aria-label="分组维度">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">不分组</SelectItem>
            <SelectItem value="tool">按工具</SelectItem>
            <SelectItem value="approver">按审批人</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={statsExporting}
          onClick={onExport}
        >
          {statsExporting ? '导出中…' : '导出统计'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={refreshing}
          onClick={onRefresh}
        >
          {refreshing ? '刷新中…' : '刷新'}
        </Button>
        <span className="text-[11px] text-muted-foreground" aria-live="polite">
          更新于 {formatStatsUpdatedAt(lastUpdatedAt)} · 页面可见时每{' '}
          {APPROVAL_STATS_REFRESH_MS / 1000} 秒自动刷新
        </span>
      </div>

      {statsExportMessage && (
        <p className={statsExportMessage.failed ? 'text-xs text-danger' : 'text-xs text-ok'}>
          {statsExportMessage.text}
        </p>
      )}

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

      {stats && (
        <Card className="py-0">
          <CardContent className="p-3">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-xs font-medium">按小时分布</div>
              <div className="text-[11px] text-muted-foreground">
                近 {stats.days} 天 · UTC · 只列有决议的小时
              </div>
            </div>
            {stats.hourly.length === 0 ? (
              <p className="text-xs text-muted-foreground">窗口内还没有已决议的审批。</p>
            ) : (
              <div className="space-y-1">
                {stats.hourly.map((hour) => (
                  <div
                    key={hour.hour}
                    className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs"
                  >
                    <span className="w-28 shrink-0 text-muted-foreground">
                      {formatHourRange(hour.hour)}
                    </span>
                    <span>{hour.decided_count} 单</span>
                    <span className="text-muted-foreground">
                      {hour.avg_wait_ms === null
                        ? '平均等待 —'
                        : `平均等待 ${formatDurationMs(hour.avg_wait_ms)}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {stats && statsGroup !== 'none' && statsGroupView === statsGroup && (
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
    </>
  );
}
