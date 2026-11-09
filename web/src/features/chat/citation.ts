/** 引用弹窗的纯逻辑：文案只依赖接口返回，便于单测（仓库前端测试都是纯函数/API）。 */

import type { KbPreview } from '@/api/kb';
import type { Citation } from './types';

/**
 * 预览底部的定位说明。
 *
 * `focused_chunk_id` 为空表示引用段在当前文档里找不到（文档更新/重传后 chunk 变了）；
 * 服务端会为引用段保留窗口，截断不会把焦点裁掉，所以这里不把「截断」当失配理由。
 *
 * 截断时必须写出**实际显示的范围**：只说「已截断」会让读者以为看到的是全文，
 * 更糟的是从中间开始的窗口会被误认为文档开头。
 */
export function describePreview(preview: KbPreview, citation: Citation): string {
  const parts: string[] = [];
  const first = preview.chunks[0]?.ord;
  const last = preview.chunks[preview.chunks.length - 1]?.ord;
  if (preview.truncated && first !== undefined && last !== undefined) {
    parts.push(`仅显示第 ${first}–${last} 段（共 ${preview.total_chunks} 段）`);
  } else {
    parts.push(`共 ${preview.total_chunks} 段`);
  }
  if (preview.focused_chunk_id === null) {
    parts.push('引用位置未找到（文档可能已更新）');
  } else {
    const focused = preview.chunks.find((chunk) => chunk.chunk_id === preview.focused_chunk_id);
    parts.push(`已定位第 ${focused?.ord ?? citation.ord} 段`);
  }
  return parts.join(' · ');
}
