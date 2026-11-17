/** 工具注册表（只读 schema + 启用/角色入口），从 ToolsPage 拆出。 */

import { FlaskConical, History, Lock, RotateCcw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ToolInfo } from '@/api/tools';

interface ToolsTableProps {
  tools: ToolInfo[];
  loading: boolean;
  busy: string | null;
  onToggle: (tool: ToolInfo) => void;
  onReset: (tool: ToolInfo) => void;
  onTest: (tool: ToolInfo) => void;
  onHistory: (tool: ToolInfo) => void;
}

export function ToolsTable({
  tools,
  loading,
  busy,
  onToggle,
  onReset,
  onTest,
  onHistory,
}: ToolsTableProps) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-0">
        {loading ? (
          <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>工具</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>超时</TableHead>
                  <TableHead>允许角色</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tools.map((tool) => (
                  <TableRow key={tool.name}>
                    <TableCell className="max-w-80 align-top">
                      <div className="font-mono text-xs font-medium">{tool.name}</div>
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        {tool.description}
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant={tool.is_write ? 'destructive' : 'secondary'}>
                        {tool.is_write ? '写操作' : '只读'}
                      </Badge>
                    </TableCell>
                    <TableCell className="align-top text-xs text-muted-foreground">
                      {tool.timeout_ms}ms
                    </TableCell>
                    <TableCell className="max-w-56 align-top text-xs">
                      {tool.roles.length === 0 ? (
                        <span className="text-muted-foreground">所有登录用户</span>
                      ) : (
                        <span className="font-mono">{tool.roles.join(' / ')}</span>
                      )}
                      {tool.overridden && (
                        <Badge variant="outline" className="ml-2 text-[10px]">
                          已覆盖
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      {!tool.code_enabled ? (
                        <Badge variant="outline" className="text-muted-foreground">
                          <Lock className="size-3" /> 代码禁用
                        </Badge>
                      ) : tool.enabled ? (
                        <Badge variant="outline" className="border-ok/30 text-ok">
                          启用
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-danger/30 text-danger">
                          已禁用
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right align-top">
                      <div className="flex flex-wrap justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => onHistory(tool)}
                        >
                          <History className="size-3" />
                          历史
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => onTest(tool)}
                        >
                          <FlaskConical className="size-3" />
                          试调用
                        </Button>
                        {tool.code_enabled && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={busy === tool.name}
                            onClick={() => onToggle(tool)}
                          >
                            {tool.enabled ? '禁用' : '启用'}
                          </Button>
                        )}
                        {tool.overridden && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={busy === tool.name}
                            title="撤销启用覆盖，角色覆盖保留"
                            onClick={() => onReset(tool)}
                          >
                            <RotateCcw className="size-3" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
