import { useState } from 'react';
import { Alert, Button, Input, Tag } from 'antd';
import { useChat } from './store';
import type { Citation } from './types';

const PHASE_LABEL: Record<string, string> = {
  idle: '就绪',
  running: '执行中',
  awaiting_approval: '等待审批',
  completed: '已完成',
  failed: '失败',
  interrupted: '已中断',
};

export default function ChatPage() {
  const { runtime, sending, send, abort, reset } = useChat();
  const [text, setText] = useState('');

  const onSend = async () => {
    const value = text.trim();
    if (!value) return;
    setText('');
    await send(value);
  };

  return (
    <>
      <div className="oncall-scroll">
        {runtime.messages.length === 0 && (
          <div className="oncall-card">
            试试：「我电脑连不上打印机了」　或　「我要申请开单报修打印机」
          </div>
        )}

        {runtime.steps.map((step) => (
          <div key={`${step.node}-${step.title}`} className="oncall-step">
            <Tag color={step.status === 'done' ? 'green' : 'processing'}>
              {step.status === 'done' ? '完成' : '进行'}
            </Tag>
            <span>
              {step.title}
              {step.summary ? ` · ${step.summary}` : ''}
            </span>
          </div>
        ))}

        {runtime.tools.map((tool) => (
          <div
            key={tool.callId}
            className={`oncall-card${tool.write ? ' oncall-card--write' : ''}`}
          >
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Tag color={tool.write ? 'orange' : 'blue'}>{tool.tool}</Tag>
              <span style={{ color: 'var(--oncall-muted)', fontSize: 12 }}>
                {tool.status}
                {tool.durationMs ? ` · ${tool.durationMs}ms` : ''}
                {tool.attempts && tool.attempts > 1 ? ` · 重试${tool.attempts - 1}次` : ''}
              </span>
            </div>
            <pre style={{ margin: '8px 0 0', fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(tool.result ?? tool.args, null, 2)}
            </pre>
            {tool.error && <div className="oncall-error">{tool.error}</div>}
          </div>
        ))}

        {runtime.approval && (
          <div className="oncall-card oncall-card--write">
            <strong>需要你确认</strong>
            <div style={{ margin: '6px 0', fontSize: 13 }}>
              即将执行 <Tag color="orange">{runtime.approval.tool}</Tag>
              {runtime.approval.reason ? `：${runtime.approval.reason}` : ''}
            </div>
            <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(runtime.approval.args, null, 2)}
            </pre>
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <Button size="small" type="primary" disabled>
                批准（W3 D14 接通）
              </Button>
              <Button size="small" disabled>
                拒绝
              </Button>
            </div>
          </div>
        )}

        {runtime.messages.map((msg) => (
          <div
            key={msg.id}
            className={msg.role === 'user' ? 'oncall-msg oncall-msg--user' : 'oncall-msg'}
          >
            {msg.text}
            {msg.streaming && <span style={{ color: 'var(--oncall-muted)' }}>▍</span>}
            {msg.citations?.length ? (
              <div style={{ marginTop: 6 }}>
                {msg.citations.map((c: Citation, i: number) => (
                  <span key={c.chunk_id} className="oncall-cite" title={c.snippet}>
                    [{i + 1}] {c.title}
                    {c.page ? ` p.${c.page}` : ''}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}

        {runtime.error && <Alert type="error" showIcon message={runtime.error} />}
      </div>

      <div className="oncall-composer">
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="描述你的问题…"
          autoSize={{ minRows: 1, maxRows: 4 }}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              void onSend();
            }
          }}
        />
        {sending ? (
          <Button danger onClick={abort}>
            停止
          </Button>
        ) : (
          <Button type="primary" onClick={() => void onSend()}>
            发送
          </Button>
        )}
        <Button onClick={reset} disabled={sending}>
          新会话
        </Button>
      </div>

      <div style={{ padding: '0 16px 10px', fontSize: 12, color: 'var(--oncall-muted)' }}>
        状态：{PHASE_LABEL[runtime.phase] ?? runtime.phase}
        {runtime.costCents !== null ? ` · 本轮成本 ¥${(runtime.costCents / 100).toFixed(2)}` : ''}
      </div>
    </>
  );
}
