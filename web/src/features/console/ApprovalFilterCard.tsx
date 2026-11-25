import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import type { ApprovalListFilters } from '@/api/approvals';

interface Props {
  initial?: ApprovalListFilters;
  onApply: (filters: ApprovalListFilters) => void;
  onClear: () => void;
}

export function ApprovalFilterCard({ initial, onApply, onClear }: Props) {
  const [tool, setTool] = useState(initial?.tool ?? '');
  const [resolvedBy, setResolvedBy] = useState(initial?.resolvedBy ?? '');
  const [from, setFrom] = useState(initial?.resolvedFrom ?? '');
  const [to, setTo] = useState(initial?.resolvedTo ?? '');
  const [error, setError] = useState<string | null>(null);

  const apply = () => {
    if (from && to && from > to) {
      setError('开始日期不能晚于结束日期');
      return;
    }
    setError(null);
    const nextTool = tool.trim();
    const nextResolvedBy = resolvedBy.trim();
    onApply({
      ...(nextTool ? { tool: nextTool } : {}),
      ...(nextResolvedBy ? { resolvedBy: nextResolvedBy } : {}),
      ...(from ? { resolvedFrom: from } : {}),
      ...(to ? { resolvedTo: to } : {}),
    });
  };

  const clear = () => {
    setTool('');
    setResolvedBy('');
    setFrom('');
    setTo('');
    setError(null);
    onClear();
  };

  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">工具</div>
            <Input
              aria-label="按工具筛选"
              className="h-8 w-40 text-xs"
              placeholder="如 create_ticket"
              value={tool}
              onChange={(event) => setTool(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">审批人</div>
            <Input
              aria-label="按审批人筛选"
              className="h-8 w-36 text-xs"
              placeholder="user_id"
              value={resolvedBy}
              onChange={(event) => setResolvedBy(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">决议开始</div>
            <Input
              aria-label="决议开始日期"
              type="date"
              className="h-8 w-36 text-xs"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">决议结束</div>
            <Input
              aria-label="决议结束日期"
              type="date"
              className="h-8 w-36 text-xs"
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
          </div>
          <Button size="sm" className="h-8 text-xs" onClick={apply}>
            筛选
          </Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clear}>
            清除
          </Button>
        </div>
        {error && <p className="mt-2 text-[11px] text-danger">{error}</p>}
        <p className="mt-2 text-[11px] text-muted-foreground">
          日期按 UTC 自然日；筛选条件会随游标绑定，改动后从第一页重新加载。
        </p>
      </CardContent>
    </Card>
  );
}
