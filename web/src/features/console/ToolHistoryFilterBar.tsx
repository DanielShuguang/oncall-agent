import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { HistoryState } from './toolHistoryFormat';

export interface ToolHistoryFilterBarProps {
  history: HistoryState;
  onChange: (state: HistoryState) => void;
  onReload: () => void;
  onClear: () => void;
  onExport: () => void;
  exporting: boolean;
  exportMessage: string | null;
}

/** 历史过滤/排序与导出入口；抽成组件避免 ToolsDialogs 超 300 行。 */
export function ToolHistoryFilterBar({
  history,
  onChange,
  onReload,
  onClear,
  onExport,
  exporting,
  exportMessage,
}: ToolHistoryFilterBarProps) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">开始日期（UTC）</div>
          <Input
            aria-label="变更开始日期"
            className="w-36"
            type="date"
            value={history.changedFrom}
            onChange={(event) => onChange({ ...history, changedFrom: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">结束日期（UTC）</div>
          <Input
            aria-label="变更结束日期"
            className="w-36"
            type="date"
            value={history.changedTo}
            onChange={(event) => onChange({ ...history, changedTo: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">变更人</div>
          <Input
            aria-label="变更人"
            className="w-36"
            placeholder="精确匹配"
            value={history.changedBy}
            onChange={(event) => onChange({ ...history, changedBy: event.target.value })}
          />
        </div>
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">来源</div>
          <Select
            value={history.source || 'all'}
            onValueChange={(value) =>
              onChange({
                ...history,
                source: value === 'all' ? '' : (value as 'tool' | 'matrix'),
              })
            }
          >
            <SelectTrigger aria-label="变更来源" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部来源</SelectItem>
              <SelectItem value="tool">管理页</SelectItem>
              <SelectItem value="matrix">权限矩阵</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">排序</div>
          <Select
            value={history.order}
            onValueChange={(value) =>
              onChange({ ...history, order: value as 'latest' | 'earliest' })
            }
          >
            <SelectTrigger aria-label="历史排序" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="latest">最新在前</SelectItem>
              <SelectItem value="earliest">最早在前</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button size="sm" variant="outline" onClick={onReload}>
          应用
        </Button>
        <Button size="sm" variant="ghost" onClick={onClear}>
          清除
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={exporting || history.loading}
          onClick={onExport}
        >
          {exporting ? '导出中…' : '导出 CSV'}
        </Button>
      </div>
      {history.filterError && <div className="text-xs text-danger">{history.filterError}</div>}
      {exportMessage && <div className="text-xs text-muted-foreground">{exportMessage}</div>}
    </div>
  );
}
