/** 知识库管理（W5 D21）：不写代码也能上传、看切片、重建索引。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileText, RefreshCw, Upload } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  getKbDocument,
  listKbDocuments,
  reindexKb,
  uploadKbDocument,
  validateKbFile,
  type KbDocument,
  type KbDocumentDetail,
} from '@/api/kb';
import { formatTime } from '@/lib/format';

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

interface DetailState {
  documentId: string;
  detail: KbDocumentDetail | null;
  loading: boolean;
  error: string | null;
}

export default function KbPage() {
  const [documents, setDocuments] = useState<KbDocument[]>([]);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // 关闭 Dialog 后，在途的详情请求不能把它重新打开
  const detailSeq = useRef(0);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await listKbDocuments();
      setDocuments(data.documents);
      setTotalChunks(data.chunk_count);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '知识库加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 首屏加载写在 effect 内：把 setState 留在 await 之后，避免同步 setState 触发级联渲染
    let cancelled = false;
    const load = async () => {
      try {
        const data = await listKbDocuments();
        if (cancelled) return;
        setDocuments(data.documents);
        setTotalChunks(data.chunk_count);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : '知识库加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const openDocument = async (documentId: string) => {
    const seq = (detailSeq.current += 1);
    setDetail({ documentId, detail: null, loading: true, error: null });
    try {
      const data = await getKbDocument(documentId);
      if (detailSeq.current === seq) {
        setDetail({ documentId, detail: data, loading: false, error: null });
      }
    } catch (exc) {
      if (detailSeq.current === seq) {
        setDetail({
          documentId,
          detail: null,
          loading: false,
          error: exc instanceof Error ? exc.message : '切片加载失败',
        });
      }
    }
  };

  const closeDocument = () => {
    detailSeq.current += 1;
    setDetail(null);
  };

  const onUpload = async (file: File) => {
    const invalid = validateKbFile(file);
    if (invalid) {
      setUploadError(invalid);
      return;
    }
    setUploading(true);
    setUploadError(null);
    setNotice(null);
    try {
      const result = await uploadKbDocument(file);
      setNotice(
        `已索引「${result.document.title}」，共 ${result.document.chunk_count} 个切片；同来源文件会覆盖旧版本。`,
      );
      await loadDocuments();
      await openDocument(result.document.id);
    } catch (exc) {
      setUploadError(exc instanceof Error ? exc.message : '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const onReindex = async () => {
    setReindexing(true);
    setUploadError(null);
    setNotice(null);
    try {
      const result = await reindexKb();
      setNotice(`已用当前 embedding 模型重算 ${result.chunks} 个切片；源文件未重新切分。`);
      await loadDocuments();
    } catch (exc) {
      setUploadError(exc instanceof Error ? exc.message : '重建索引失败');
    } finally {
      setReindexing(false);
    }
  };

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return documents;
    return documents.filter(
      (doc) =>
        doc.title.toLowerCase().includes(keyword) || doc.source.toLowerCase().includes(keyword),
    );
  }, [documents, query]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1.4fr_1fr]">
        <Card className="gap-0 py-0">
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Upload className="size-4 text-brand" />
                上传知识文档
              </div>
              <p className="mt-1 mb-0 text-xs text-muted-foreground">
                支持 PDF / DOCX / MD / TXT；扫描 PDF 返回 PARSE_FAILED（v1 不做 OCR）。
                同一来源再次上传会覆盖旧文档。
              </p>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.md,.markdown,.txt"
              className="hidden"
              aria-label="选择知识文档"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // 先清空 value，才能连续两次选择同一个文件触发 change
                event.target.value = '';
                if (file) void onUpload(file);
              }}
            />
            <Button
              size="sm"
              disabled={uploading || reindexing}
              onClick={() => fileInput.current?.click()}
            >
              {uploading ? '上传并索引中…' : '选择文件'}
            </Button>
          </CardContent>
        </Card>

        <Card className="gap-0 py-0">
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold">重建索引</div>
              <p className="mt-1 mb-0 text-xs text-muted-foreground">
                换 embedding 模型后重算全部向量，不重新切分源文件。
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={reindexing || uploading}
              onClick={onReindex}
            >
              <RefreshCw className={reindexing ? 'size-3.5 animate-spin' : 'size-3.5'} />
              {reindexing ? '重建中…' : '重建'}
            </Button>
          </CardContent>
        </Card>
      </div>

      {uploadError && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{uploadError}</CardContent>
        </Card>
      )}
      {notice && (
        <Card className="border-ok/30 bg-ok/5">
          <CardContent className="p-3 text-xs text-ok">{notice}</CardContent>
        </Card>
      )}
      {error && (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="p-3 text-xs text-danger">{error}</CardContent>
        </Card>
      )}

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
              onChange={(event) => setQuery(event.target.value)}
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
                          onClick={() => void openDocument(doc.id)}
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
                          className={STATUS_TONES[doc.status] ?? 'text-muted-foreground'}
                        >
                          {STATUS_LABELS[doc.status] ?? doc.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatTime(doc.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => void openDocument(doc.id)}
                        >
                          切片
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        口径：列表来自 <code>kb_documents</code>；切片预览按 <code>ord</code> 升序，最多 200 条，
        超出部分以 <code>chunk_count</code> 为准。上传响应只回前 50 条。
      </p>

      <Dialog
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) closeDocument();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{detail?.detail?.document.title ?? '切片预览'}</DialogTitle>
            <DialogDescription>
              {detail?.detail ? (
                <>
                  {detail.detail.document.source} · 共 {detail.detail.document.chunk_count} 个切片 ·
                  预览 {detail.detail.chunks.length} 条
                </>
              ) : (
                '正在读取文档切片…'
              )}
            </DialogDescription>
          </DialogHeader>

          {detail?.loading && (
            <div className="py-8 text-center text-xs text-muted-foreground">加载中…</div>
          )}
          {detail?.error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 p-3 text-xs text-danger">
              {detail.error}
            </div>
          )}
          {detail?.detail && (
            <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
              {detail.detail.chunks.map((chunk) => (
                <div key={`${chunk.ord}-${chunk.heading ?? ''}`} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">#{chunk.ord}</Badge>
                    <span className="text-xs font-medium">{chunk.heading ?? '（无标题路径）'}</span>
                    {chunk.page !== null && (
                      <span className="text-[11px] text-muted-foreground">第 {chunk.page} 页</span>
                    )}
                  </div>
                  <p className="mt-2 mb-0 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
                    {chunk.content}
                  </p>
                </div>
              ))}
              {detail.detail.chunks.length === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">
                  该文档没有切片。
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
