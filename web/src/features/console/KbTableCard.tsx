import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
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
import type { KbDocument } from '@/api/kb';
import { formatTime } from '@/lib/format';
import { accessLabel, isRestricted } from './access';

const STATUS_TONES: Record<string, string> = {
  indexed: 'border-ok/20 bg-ok/10 text-ok',
  pending: 'border-warn/20 bg-warn/10 text-warn',
  failed: 'border-danger/20 bg-danger/10 text-danger',
};

const STATUS_LABELS: Record<string, string> = {
  indexed: '已索引',
  pending: '处理中',
  failed: '失败',
};

interface Props {
  documents: KbDocument[];
  filtered: KbDocument[];
  totalChunks: number;
  loading: boolean;
  query: string;
  onChangeQuery: (value: string) => void;
  onOpenDocument: (documentId: string) => void;
  onOpenAccess: (document: KbDocument) => void;
}

export function KbTableCard({
  documents,
  filtered,
  totalChunks,
  loading,
  query,
  onChangeQuery,
  onOpenDocument,
  onOpenAccess,
}: Props) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
          <div className="text-sm font-semibold">文档列表</div>
          <Badge variant="secondary">
            {documents.length} 篇 · {totalChunks} 切片
          </Badge>
          <Input
            value={query}
            aria-label="筛选文档"
            placeholder="按标题或来源筛选…"
            className="ml-auto h-8 w-full text-xs sm:w-56"
            onChange={(event) => onChangeQuery(event.target.value)}
          />
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-muted-foreground">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-xs text-muted-foreground">
            {documents.length === 0 ? '知识库还是空的，上传第一篇文档试试。' : '没有匹配的文档。'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>来源</TableHead>
                  <TableHead className="text-right">切片</TableHead>
                  <TableHead>可见范围</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="max-w-64">
                      <button
                        type="button"
                        className="flex min-w-0 items-center gap-2 text-left text-xs hover:text-brand"
                        onClick={() => onOpenDocument(doc.id)}
                      >
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate font-medium">{doc.title}</span>
                      </button>
                    </TableCell>
                    <TableCell className="max-w-48 truncate text-xs text-muted-foreground">
                      {doc.source}
                    </TableCell>
                    <TableCell className="text-right text-xs">{doc.chunk_count}</TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={
                          isRestricted(doc)
                            ? 'border-warn/20 bg-warn/10 text-warn'
                            : 'text-muted-foreground'
                        }
                      >
                        {accessLabel(doc)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={STATUS_TONES[doc.status] ?? 'text-muted-foreground'}
                      >
                        {STATUS_LABELS[doc.status] ?? doc.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatTime(doc.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => onOpenDocument(doc.id)}
                        >
                          切片
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => onOpenAccess(doc)}
                        >
                          范围
                        </Button>
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
