/** 知识库管理接口。契约见 docs/03-api-contract.md §5。 */

import { getJson, postForm } from './client';

export interface KbDocument {
  id: string;
  title: string;
  source: string;
  version: string | null;
  checksum: string;
  chunk_count: number;
  status: string;
  created_at: string;
}

export interface KbChunk {
  ord: number;
  heading: string | null;
  content: string;
  page: number | null;
  is_table?: boolean;
}

export interface KbDocumentList {
  documents: KbDocument[];
  total: number;
  chunk_count: number;
}

export interface KbDocumentDetail {
  document: KbDocument;
  chunks: KbChunk[];
}

export interface KbUploadResult {
  document: KbDocument;
  chunks: KbChunk[];
}

export interface KbReindexResult {
  chunks: number;
}

export function listKbDocuments(): Promise<KbDocumentList> {
  return getJson<KbDocumentList>('/admin/kb/documents');
}

export function getKbDocument(documentId: string, preview = 200): Promise<KbDocumentDetail> {
  return getJson<KbDocumentDetail>(
    `/admin/kb/documents/${encodeURIComponent(documentId)}?preview=${preview}`,
  );
}

export function uploadKbDocument(file: File): Promise<KbUploadResult> {
  const form = new FormData();
  form.append('file', file);
  return postForm<KbUploadResult>('/admin/kb/documents', form);
}

export function reindexKb(): Promise<KbReindexResult> {
  return getJson<KbReindexResult>('/admin/kb/reindex', { method: 'POST' });
}

/**
 * 只做扩展名校验；大小上限由服务端 `ONCALL_KB_MAX_UPLOAD_MB` 决定，
 * 前端不复制这个配置，避免两处默认值漂移后把合法文件挡在门外。
 */
export function validateKbFile(file: File): string | null {
  const name = file.name.toLowerCase();
  const allowed = ['.pdf', '.docx', '.md', '.markdown', '.txt'];
  if (!allowed.some((suffix) => name.endsWith(suffix))) {
    return '仅支持 PDF / DOCX / MD / TXT';
  }
  return null;
}
