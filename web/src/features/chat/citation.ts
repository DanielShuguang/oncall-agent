/** 引用弹窗的纯逻辑：文案只依赖接口返回，便于单测（仓库前端测试都是纯函数/API）。 */

import type { KbPreview } from '@/api/kb';
import type { Citation } from './types';

/**
 * 预览底部的定位说明。
 *
 * `focused_chunk_id` 为空表示引用段在当前文档里找不到（文档更新/重传后 chunk 变了）；
 * 服务端会为引用段保留窗口，截断不会把焦点裁掉，所以这里不把「截断」当失配理由。
 */
export function describePreview(preview: KbPreview, citation: Citation): string {
  const parts = [`共 ${preview.total_chunks} 段`];
  if (preview.focused_chunk_id === null) {
    parts.push('引用位置未找到（文档可能已更新）');
  } else {
    const focused = preview.chunks.find((chunk) => chunk.chunk_id === preview.focused_chunk_id);
    parts.push(`已定位第 ${focused?.ord ?? citation.ord} 段`);
  }
  if (preview.truncated) parts.push('超长已截断');
  return parts.join(' · ');
}
