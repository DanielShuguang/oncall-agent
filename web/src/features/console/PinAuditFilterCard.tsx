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
import type { SessionPinAction } from '@/api/pinAudits';
import { AUDIT_DATE_PRESETS, type AuditDatePreset } from './auditDatePresets';

export type ActionFilter = 'all' | SessionPinAction;
export type PinAuditDraft = {
  userId: string;
  sessionId: string;
  action: ActionFilter;
  from: string;
  to: string;
};

export const EMPTY_PIN_AUDIT_DRAFT: PinAuditDraft = {
  userId: '',
  sessionId: '',
  action: 'all',
  from: '',
  to: '',
};

export function PinAuditFilterCard({
  draft,
  activePreset,
  error,
  onChange,
  onApplyPreset,
  onApply,
  onClear,
}: {
  draft: PinAuditDraft;
  activePreset: AuditDatePreset | null;
  error: string | null;
  onChange: (patch: Partial<PinAuditDraft>) => void;
  onApplyPreset: (preset: AuditDatePreset) => void;
  onApply: () => void;
  onClear: () => void;
}) {
  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-muted-foreground">快捷日期（UTC）</span>
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
