import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { SessionPinAuditStats } from '@/api/pinAudits';

export const STATS_DAYS = [7, 30, 90] as const;

export function PinAuditStatsCard({
  stats,
  loading,
  error,
  days,
  filtered,
  dateRangeActive,
  onChangeDays,
}: {
  stats: SessionPinAuditStats | null;
  loading: boolean;
  error: string | null;
  days: number;
  filtered: boolean;
  dateRangeActive: boolean;
  onChangeDays: (days: number) => void;
}) {
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 p-3">
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium text-foreground">
              置顶活动 · {filtered ? '已应用筛选' : '全部用户'}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {dateRangeActive
                ? '统计跟随下方已应用的日期范围'
                : filtered
                  ? '统计跟随下方已应用的用户/会话/动作筛选'
                  : '全局窗口统计，不随下方筛选变化'}
            </div>
          </div>
          {dateRangeActive ? (
            <span className="rounded border bg-canvas/40 px-2 py-1 text-[11px] text-muted-foreground">
              按筛选日期{stats ? `（${stats.days} 天）` : ''}
            </span>
          ) : (
            <div className="flex gap-1">
              {STATS_DAYS.map((value) => (
                <Button
                  key={value}
                  variant={days === value ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 text-[11px]"
                  aria-pressed={days === value}
                  onClick={() => onChangeDays(value)}
                >
                  近 {value} 天
                </Button>
              ))}
            </div>
          )}
        </div>
        {loading ? (
          <p className="text-xs text-muted-foreground">统计加载中…</p>
        ) : error ? (
          <p className="text-xs text-danger">统计暂不可用：{error}</p>
        ) : stats ? (
          <>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <Stat label="置顶" value={stats.pins} />
              <Stat label="取消置顶" value={stats.unpins} />
              <Stat label="涉及用户" value={stats.users} />
              <Stat label="涉及会话" value={stats.sessions} />
            </div>
            {stats.daily.length > 0 ? (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {stats.daily.slice(-7).map((day) => (
                    <span
                      key={day.day}
                      className="rounded border bg-canvas/40 px-2 py-1 text-[11px] text-muted-foreground"
                    >
                      {day.day.slice(5)} · 置顶 {day.pins} / 取消 {day.unpins}
                    </span>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  UTC 自然日；只列最近 {Math.min(7, stats.daily.length)} 个有活动的日期。
                </p>
              </>
            ) : (
              <p className="text-[11px] text-muted-foreground">窗口内没有置顶/取消置顶记录。</p>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}
