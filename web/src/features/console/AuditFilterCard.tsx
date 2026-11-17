/** 恢复审计过滤卡（ADR-0063/0067/0075/0078）。 */

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AUDIT_DATE_PRESETS, type AuditDatePreset } from './auditDatePresets';

interface AuditFilterCardProps {
  userId: string;
  sessionId: string;
  from: string;
  to: string;
  activePreset: AuditDatePreset | null;
  error: string | null;
  onChangeUserId: (value: string) => void;
  onChangeSessionId: (value: string) => void;
  onChangeFrom: (value: string) => void;
  onChangeTo: (value: string) => void;
  onApplyPreset: (preset: AuditDatePreset) => void;
  onApply: () => void;
  onClear: () => void;
}

export function AuditFilterCard({
  userId,
  sessionId,
  from,
  to,
  activePreset,
  error,
  onChangeUserId,
  onChangeSessionId,
  onChangeFrom,
  onChangeTo,
  onApplyPreset,
  onApply,
  onClear,
}: AuditFilterCardProps) {
  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-muted-foreground">快捷日期（记住上次选择）</span>
          {AUDIT_DATE_PRESETS.map((preset) => (
            <Button
              key={preset.value}
              variant={activePreset === preset.value ? 'default' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-xs"
              aria-pressed={activePreset === preset.value}
              onClick={() => onApplyPreset(preset.value)}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">用户</div>
            <Input
              aria-label="按用户筛选恢复审计"
              className="h-8 w-40 text-xs"
              placeholder="user_id"
              maxLength={64}
              value={userId}
              onChange={(event) => onChangeUserId(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">会话</div>
            <Input
              aria-label="按会话筛选恢复审计"
              className="h-8 w-48 text-xs"
              placeholder="session_id"
              maxLength={64}
              value={sessionId}
              onChange={(event) => onChangeSessionId(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">开始日期</div>
            <Input
              type="date"
              aria-label="按恢复开始日期筛选"
              className="h-8 w-36 text-xs"
              value={from}
              onChange={(event) => onChangeFrom(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">结束日期</div>
            <Input
              type="date"
              aria-label="按恢复结束日期筛选"
              className="h-8 w-36 text-xs"
              value={to}
              onChange={(event) => onChangeTo(event.target.value)}
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
          用户与会话均为精确匹配；session_id 走 JSONB 包含查询，可定位「这个会话被谁恢复过」。
          日期按 UTC 自然日闭区间，最多 365 天，需同时选择起止；统计与导出沿用同一组过滤。
        </p>
      </CardContent>
    </Card>
  );
}
