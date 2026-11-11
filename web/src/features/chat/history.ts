/** 历史会话的只读 transcript（ADR-0030）。
 *
 * 服务端只保存 run 的 input/output，不保存前端消息 id 与草稿；回看时按时间顺序
 * 拼成对话气泡。正文过了保留期（ADR-0023）或引用被回收（ADR-0022）时给出
 * 明确的占位说明，不能让人以为是「模型没回答」。
 */

import type { RunDetail } from '@/api/runs';
import type { ChatMessage } from './types';

export const PRUNED_NOTE = '（正文已过保留期，不再展示）';
export const REDACTED_NOTE = '（回答引用的文档已不可见，内容不再展示）';
export const RUNNING_NOTE = '（这场对话还没有结束）';
export const FAILED_NOTE = '（这场对话没有生成回答）';

export function transcriptMessages(runs: RunDetail[]): ChatMessage[] {
  // 有序插入而不是 sort：ES2022 库没有 toSorted，oxlint 也不允许原地 sort
  const ordered: RunDetail[] = [];
  for (const run of runs) {
    let index = ordered.length;
    while (index > 0) {
      const previous = ordered[index - 1];
      if (previous === undefined) break;
      const inOrder =
        previous.started_at < run.started_at ||
        (previous.started_at === run.started_at && previous.run_id <= run.run_id);
      if (inOrder) break;
      index -= 1;
    }
    ordered.splice(index, 0, run);
  }
  const messages: ChatMessage[] = [];
  for (const run of ordered) {
    const userText = run.input || (run.content_pruned_at ? PRUNED_NOTE : '（没有输入）');
    messages.push({ id: `hist_${run.run_id}_u`, role: 'user', text: userText });

    let answer: string;
    if (run.content_redacted) answer = REDACTED_NOTE;
    else if (run.output) answer = run.output;
    else if (run.content_pruned_at) answer = PRUNED_NOTE;
    else if (run.status === 'running' || run.status === 'awaiting_approval') answer = RUNNING_NOTE;
    else if (run.status === 'failed' || run.error_code) answer = FAILED_NOTE;
    else answer = '（没有回答内容）';
    // 引用快照只在正文可见时还原（ADR-0031）；否则角标会指向一段看不到的答案
    const citations = !run.content_redacted && run.output ? run.citations : [];
    messages.push({
      id: `hist_${run.run_id}_a`,
      role: 'assistant',
      text: answer,
      citations: citations.length ? citations : undefined,
    });
  }
  return messages;
}
