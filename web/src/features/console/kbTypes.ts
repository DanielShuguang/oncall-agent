import type { KbDocument, KbDocumentDetail } from '@/api/kb';
import type { Visibility } from './access';

export interface KbDetailState {
  documentId: string;
  detail: KbDocumentDetail | null;
  loading: boolean;
  error: string | null;
}

export interface KbAccessDialogState {
  document: KbDocument;
  visibility: Visibility;
  rolesText: string;
  saving: boolean;
  error: string | null;
}
