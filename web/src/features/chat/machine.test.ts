import { describe, expect, it } from 'vitest';
import { initialRuntime, nextPhase, runtimeReducer, type Runtime } from './machine';
import { parseFrame } from './stream';
import type { RunEvent } from './types';

const evt = (type: string, payload: Record<string, unknown> = {}, seq = 1): RunEvent => ({
  seq,
  run_id: 'r1',
  type,
  ts: new Date().toISOString(),
  payload,
});

const running = (): Runtime => ({ ...initialRuntime, phase: 'running' });

describe('状态机转移', () => {
  it('idle 收到 SEND 进入 running', () => {
    expect(nextPhase('idle', 'SEND')).toBe('running');
  });

  it('running 收到 approval.required 进入 awaiting_approval', () => {
    expect(nextPhase('running', 'approval.required')).toBe('awaiting_approval');
  });

  it('非法转移返回 null（不抛错）', () => {
    expect(nextPhase('idle', 'message.delta')).toBeNull();
    expect(nextPhase('completed', 'approval.required')).toBeNull();
  });
});

describe('事件归约', () => {
  it('message.delta 累积到同一条助手消息', () => {
    let rt = running();
    rt = runtimeReducer(rt, evt('message.delta', { text: '你' }));
    rt = runtimeReducer(rt, evt('message.delta', { text: '好' }, 2));
    expect(rt.messages).toHaveLength(1);
    expect(rt.messages[0].text).toBe('你好');
  });

  it('tool.call 与 tool.result 通过 call_id 匹配', () => {
    let rt = running();
    rt = runtimeReducer(
      rt,
      evt('tool.call', { call_id: 'c1', tool: 'query_cmdb', args: { owner_id: 'u' } }),
    );
    rt = runtimeReducer(
      rt,
      evt('tool.result', { call_id: 'c1', tool: 'query_cmdb', status: 'ok', duration_ms: 120 }, 2),
    );
    expect(rt.tools[0].status).toBe('ok');
    expect(rt.tools[0].durationMs).toBe(120);
  });

  it('approval.required 也会结束流式光标', () => {
    let rt = running();
    rt = runtimeReducer(rt, evt('message.delta', { text: '部分' }));
    rt = runtimeReducer(
      rt,
      evt(
        'approval.required',
        { approval_id: 'apr_1', tool: 'create_ticket', args: {}, risk_level: 'medium' },
        2,
      ),
    );

    expect(rt.phase).toBe('awaiting_approval');
    expect(rt.messages[0].streaming).toBe(false);
  });

  it('未知事件被忽略且状态不变', () => {
    const next = runtimeReducer(running(), evt('some.future.event', { x: 1 }));
    expect(next.phase).toBe('running');
    expect(next.messages).toHaveLength(0);
  });

  it('run.started 记录 run_id（断线补拉的唯一依据）', () => {
    const next = runtimeReducer(running(), evt('run.started', { model: 'mock' }));
    expect(next.runId).toBe('r1');
  });

  it('run.failed 记录错误信息并结束流式光标', () => {
    let rt = running();
    rt = runtimeReducer(rt, evt('message.delta', { text: '部分' }));
    expect(rt.messages[0].streaming).toBe(true);

    rt = runtimeReducer(rt, evt('run.failed', { message: '模型超时' }, 2));
    expect(rt.phase).toBe('failed');
    expect(rt.error).toBe('模型超时');
    expect(rt.messages[0].streaming).toBe(false);
  });
});

describe('SSE 帧解析', () => {
  it('解析 id/event/data', () => {
    const frame = parseFrame('id: 7\nevent: message.delta\ndata: {"seq":7}');
    expect(frame).toEqual({ id: '7', event: 'message.delta', data: '{"seq":7}' });
  });

  it('忽略心跳注释行', () => {
    expect(parseFrame(': heartbeat')).toBeNull();
  });
});

describe('审批恢复', () => {
  it('恢复后的 message.delta 复用挂起前的占位消息', () => {
    let rt: Runtime = { ...running(), runId: 'r1' };
    rt = runtimeReducer(rt, evt('approval.required', { approval_id: 'a1', tool: 'create_ticket' }));
    rt = runtimeReducer(rt, evt('approval.resolved', { approval_id: 'a1', status: 'approved' }, 2));
    rt = runtimeReducer(rt, evt('message.delta', { text: '已创建' }, 3));
    rt = runtimeReducer(rt, evt('message.completed', { text: '已创建', citations: [] }, 4));

    expect(rt.messages).toHaveLength(1);
    expect(rt.messages[0].text).toBe('已创建');
    expect(rt.messages[0].streaming).toBe(false);
    expect(rt.phase).toBe('running');
  });
});
