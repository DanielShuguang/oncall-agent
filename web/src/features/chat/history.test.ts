import { describe, expect, it } from 'vitest';
import type { RunDetail } from '@/api/runs';
import {
  FAILED_NOTE,
  PRUNED_NOTE,
  REDACTED_NOTE,
  RUNNING_NOTE,
  transcriptMessages,
} from './history';

function run(overrides: Partial<RunDetail> & { run_id: string; started_at: string }): RunDetail {
  return {
    status: 'completed',
    user_id: 'u_102',
    session_id: 'sess_1',
    intent: null,
    model: null,
    step_count: 1,
    max_steps: 12,
    token_in: 0,
    token_out: 0,
    cost_cents: 0,
    error_code: null,
    failure_category: null,
    event_count: 1,
    events_pruned_at: null,
    content_pruned_at: null,
    finished_at: null,
    input: '问题',
    output: '回答',
    content_redacted: false,
    model_calls: [],
    ...overrides,
  };
}

describe('transcriptMessages', () => {
  it('按时间排序并配对 user/assistant', () => {
    const messages = transcriptMessages([
      run({ run_id: 'b', started_at: '2026-11-08T00:01:00Z', input: '第二问', output: '第二答' }),
      run({ run_id: 'a', started_at: '2026-11-08T00:00:00Z', input: '第一问', output: '第一答' }),
    ]);
    expect(messages.map((message) => message.role)).toEqual([
      'user',
      'assistant',
      'user',
      'assistant',
    ]);
    expect(messages.map((message) => message.text)).toEqual([
      '第一问',
      '第一答',
      '第二问',
      '第二答',
    ]);
    expect(messages[0]?.id).toBe('hist_a_u');
    expect(messages[1]?.id).toBe('hist_a_a');
  });

  it('正文清理、引用回收、未结束与失败各有明确占位', () => {
    const messages = transcriptMessages([
      run({
        run_id: 'p',
        started_at: '2026-11-08T00:00:00Z',
        input: '',
        output: null,
        content_pruned_at: '2026-12-01T00:00:00Z',
      }),
      run({
        run_id: 'r',
        started_at: '2026-11-08T00:01:00Z',
        output: null,
        content_redacted: true,
      }),
      run({ run_id: 'g', started_at: '2026-11-08T00:02:00Z', status: 'running', output: null }),
      run({
        run_id: 'f',
        started_at: '2026-11-08T00:03:00Z',
        status: 'failed',
        output: null,
        error_code: 'TOOL_ERROR',
      }),
    ]);
    const answers = messages.filter((message) => message.role === 'assistant').map((m) => m.text);
    expect(answers).toEqual([PRUNED_NOTE, REDACTED_NOTE, RUNNING_NOTE, FAILED_NOTE]);
    expect(messages[0]?.text).toBe(PRUNED_NOTE);
  });
});
