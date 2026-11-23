import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  APPROVAL_STATS_REFRESH_INTERVAL_MAX,
  APPROVAL_STATS_REFRESH_INTERVAL_MIN,
  APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS,
  formatStatsUpdatedAt,
  type ApprovalStatsRefreshSeconds,
} from './approvalStatsRefresh';

interface Props {
  autoRefreshEnabled: boolean;
  autoRefreshError: string | null;
  lastUpdatedAt: number | null;
  refreshing: boolean;
  refreshIntervalSec: ApprovalStatsRefreshSeconds;
  onToggleAutoRefresh: (enabled: boolean) => void;
  onChangeRefreshInterval: (seconds: ApprovalStatsRefreshSeconds) => void;
  onRefresh: () => void;
}

/** 自动刷新开关与间隔；从统计面板拆出，避免单文件超 300 行。 */
export function ApprovalStatsRefreshControls({
  autoRefreshEnabled,
  autoRefreshError,
  lastUpdatedAt,
  refreshing,
  refreshIntervalSec,
  onToggleAutoRefresh,
  onChangeRefreshInterval,
  onRefresh,
}: Props) {
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8 text-xs"
        disabled={refreshing}
        onClick={onRefresh}
      >
        {refreshing ? '刷新中…' : '刷新'}
      </Button>
      <Button
        variant={autoRefreshEnabled ? 'secondary' : 'ghost'}
        size="sm"
        className="h-8 text-xs"
        aria-pressed={autoRefreshEnabled}
        onClick={() => onToggleAutoRefresh(!autoRefreshEnabled)}
      >
        自动刷新：{autoRefreshEnabled ? '开' : '关'}
      </Button>
      <Select
        value={
          APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS.some((option) => option === refreshIntervalSec)
            ? String(refreshIntervalSec)
            : 'custom'
        }
        onValueChange={(next) => onChangeRefreshInterval(next === 'custom' ? 45 : Number(next))}
      >
        <SelectTrigger className="h-8 w-32 text-xs" aria-label="自动刷新间隔">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS.map((seconds) => (
            <SelectItem key={seconds} value={String(seconds)}>
              {seconds} 秒
            </SelectItem>
          ))}
          <SelectItem value="custom">自定义…</SelectItem>
        </SelectContent>
      </Select>
      <Input
        key={refreshIntervalSec}
        type="number"
        min={APPROVAL_STATS_REFRESH_INTERVAL_MIN}
        max={APPROVAL_STATS_REFRESH_INTERVAL_MAX}
        defaultValue={refreshIntervalSec}
        aria-label="自定义刷新间隔（5–300 秒）"
        title="自定义刷新间隔：5–300 秒，回车或失焦应用"
        className="h-8 w-20 text-xs"
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
        onBlur={(event) => {
          const next = Number(event.currentTarget.value);
          if (
            Number.isInteger(next) &&
            next >= APPROVAL_STATS_REFRESH_INTERVAL_MIN &&
            next <= APPROVAL_STATS_REFRESH_INTERVAL_MAX
          ) {
            onChangeRefreshInterval(next);
          } else {
            event.currentTarget.value = String(refreshIntervalSec);
          }
        }}
      />
      <span className="text-[11px] text-muted-foreground" aria-live="polite">
        更新于 {formatStatsUpdatedAt(lastUpdatedAt)} ·{' '}
        {autoRefreshEnabled ? `页面可见时每 ${refreshIntervalSec} 秒自动刷新` : '自动刷新已暂停'}
      </span>
      {autoRefreshError && <p className="text-xs text-warn">{autoRefreshError}</p>}
    </>
  );
}
