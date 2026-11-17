/** 知识库管理（W5 D21）：不写代码也能上传、看切片、重建索引。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import {
  getKbDocument,
  listKbDocuments,
  reindexKb,
  updateKbAccess,
  uploadKbDocument,
  validateKbFile,
  type KbDocument,
} from '@/api/kb';
import { accessLabel, draftOf, parseRoleInput, type Visibility } from './access';
import { KbDialogs } from './KbDialogs';
import { KbTableCard } from './KbTableCard';
import { KbUploadCards } from './KbUploadCards';
import type { KbAccessDialogState, KbDetailState } from './kbTypes';

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
  const [visibility, setVisibility] = useState<Visibility>('public');
  const [rolesText, setRolesText] = useState('');
  const [accessDialog, setAccessDialog] = useState<KbAccessDialogState | null>(null);
  const [detail, setDetail] = useState<KbDetailState | null>(null);
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

  const openAccessDialog = (document: KbDocument) => {
    const draft = draftOf(document);
    setAccessDialog({
      document,
      visibility: draft.visibility,
      rolesText: draft.rolesText,
      saving: false,
      error: null,
    });
  };

  const onSaveAccess = async () => {
    const draft = accessDialog;
    if (!draft) return;
    const parsed = parseRoleInput(draft.rolesText);
    if (draft.visibility === 'roles' && (parsed.error || parsed.roles.length === 0)) {
      setAccessDialog({
        ...draft,
        error: parsed.error ?? '指定角色可见时至少要填一个角色',
      });
      return;
    }
    setAccessDialog({ ...draft, saving: true, error: null });
    try {
      const updated = await updateKbAccess(draft.document.id, {
        visibility: draft.visibility,
        roles: draft.visibility === 'roles' ? parsed.roles : [],
      });
      setDocuments((previous) =>
        previous.map((document) => (document.id === updated.id ? updated : document)),
      );
      setNotice(
        `「${updated.title}」可见范围已改为${accessLabel(updated)}；不重新切分，已有引用仍然可用。`,
      );
      setAccessDialog(null);
    } catch (exc) {
      setAccessDialog({
        ...draft,
        saving: false,
        error: exc instanceof Error ? exc.message : '可见范围保存失败',
      });
    }
  };

  const onUpload = async (file: File) => {
    const invalid = validateKbFile(file);
    if (invalid) {
      setUploadError(invalid);
      return;
    }
    const parsed = parseRoleInput(rolesText);
    if (visibility === 'roles' && (parsed.error || parsed.roles.length === 0)) {
      setUploadError(parsed.error ?? '指定角色可见时至少要填一个角色');
      return;
    }
    setUploading(true);
    setUploadError(null);
    setNotice(null);
    try {
      const result = await uploadKbDocument(file, {
        visibility,
        roles: visibility === 'roles' ? parsed.roles : [],
      });
      setNotice(
        `已索引「${result.document.title}」，共 ${result.document.chunk_count} 个切片` +
          `（${accessLabel(result.document)}）；同来源文件会覆盖旧版本。`,
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
      <KbUploadCards
        uploading={uploading}
        reindexing={reindexing}
        visibility={visibility}
        rolesText={rolesText}
        onUpload={(file) => void onUpload(file)}
        onReindex={() => void onReindex()}
        onChangeVisibility={setVisibility}
        onChangeRolesText={setRolesText}
      />

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

      <KbTableCard
        documents={documents}
        filtered={filtered}
        totalChunks={totalChunks}
        loading={loading}
        query={query}
        onChangeQuery={setQuery}
        onOpenDocument={(id) => void openDocument(id)}
        onOpenAccess={openAccessDialog}
      />

      <p className="text-[11px] text-muted-foreground">
        口径：列表来自 <code>kb_documents</code>；切片预览按 <code>ord</code> 升序，最多 200 条，
        超出部分以 <code>chunk_count</code> 为准。上传响应只回前 50 条。
        「指定角色」的文档在检索阶段就被过滤：员工看不到它，管理员（知识库所有者）始终可读。
      </p>

      <KbDialogs
        detail={detail}
        accessDialog={accessDialog}
        setAccessDialog={setAccessDialog}
        onCloseDetail={closeDocument}
        onSaveAccess={() => void onSaveAccess()}
      />
    </div>
  );
}
