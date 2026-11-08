# 07 · 前端设计

## 1. 目标

前端在这个项目里的角色不是"画界面"，而是**把不可靠的 Agent 变成可理解的界面**：

- 让用户看到 Agent 在做什么（步骤、工具、参数）
- 让用户在关键处能拦住（审批、中断）
- 让断线、超时、失败都有明确出口（续传、重试、转人工）

## 2. 路由

| 路径 | 页面 | 阶段 |
|---|---|---|
| `/` | 对话（员工视角） | W1 D3 |
| `/runs` | 运行列表 | W4 D19 |
| `/runs/:id` | 运行详情 / 回放 | W4 D20 |
| `/console/kb` | 知识库管理 | W5 D21 |
| `/console/tools` | 工具注册 | W5 D22 |
| `/console/perms` | 权限矩阵 | W5 D23 |
| `/console/approvals` | 审批中心 | W5 D23 |
| `/console/cost` | 成本看板 | W4 D19 |

## 3. 状态机

Agent 界面最容易写崩的地方是"用一堆 boolean 拼状态"。这里用显式状态 + 转移表。

```ts
export type ChatPhase =
  | 'idle'               // 可输入
  | 'running'            // Agent 执行中
  | 'awaiting_approval'  // 等待人工审批
  | 'completed'          // 本轮完成
  | 'failed'             // 失败（可重试）
  | 'interrupted'        // 用户中断 / 断线
```

| 事件 \ 状态 | idle | running | awaiting_approval | completed | failed | interrupted |
|---|---|---|---|---|---|---|
| `SEND` | running | — | — | running | running | running |
| `run.started` | — | running | — | running | running | — |
| `step.*` / `tool.*` / `message.*` | — | running | — | — | — | — |
| `approval.required` | — | **awaiting_approval** | — | — | — | — |
| `approval.resolved` | — | running | running | — | — | — |
| `run.completed` | — | **completed** | — | — | — | — |
| `run.failed` | — | **failed** | failed | — | — | — |
| `ABORT`（用户） | — | interrupted | interrupted | — | — | — |
| `RECONNECTED` | — | running | running | — | — | **running** |
| `RESET` | idle | — | — | idle | idle | idle |

非法转移**直接丢弃并打日志**（不要 throw，线上会炸）。

实现：`src/features/chat/machine.ts`（纯函数 reducer + `TRANSITIONS` 表），配单测覆盖所有非法转移。

## 4. 流式客户端

不用 `EventSource`，因为需要 POST + 鉴权头：

```ts
const res = await fetch('/api/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  body: JSON.stringify(payload),
  signal,                        // AbortController 支持用户中断
});
const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
```

解析要点：

1. 按 `\n\n` 分帧，**不要按 `\n`**（data 里可能有换行）
2. 每帧解析 `id:` / `event:` / `data:` 三类行
3. `: heartbeat` 注释行忽略，但可用于探测"连接是否还活着"
4. 缓冲区要处理"半帧"（上一次读到的最后一段可能不完整）

## 5. 组件树

```
ChatPage
├─ ConversationList        历史会话
├─ MessageList             虚拟滚动（长会话）
│  ├─ UserMessage
│  ├─ AssistantMessage
│  │  ├─ MarkdownText      流式中渲染，代码块/表格
│  │  └─ CitationList      角标 [1][2]，点击跳原文
│  ├─ StepTimeline         step.started/completed
│  ├─ ToolCard             tool.call/result：参数、状态、耗时、错误
│  └─ ApprovalCard         approval.required
│     ├─ ArgsPreview       参数人类可读化（不是裸 JSON）
│     ├─ RiskBadge         风险等级
│     └─ Actions           批准 / 拒绝 / 本会话允许
├─ Composer                输入框，Enter 发送，Shift+Enter 换行
└─ ConnectionBanner        断线提示 + "正在恢复…"
```

管理后台：

```
ConsoleLayout（侧边导航）
├─ KbPage         上传、列表、切片预览、重建索引
├─ ToolsPage      工具卡片、Schema 编辑、试调用
├─ PermsPage      角色 × 工具矩阵（勾选即保存）
├─ ApprovalsPage  待办/已办，支持批量
└─ CostPage       日/模型/用户三段聚合 + 趋势图 + Top 花费 run
```

## 6. 交互细节（这些才是"体验"）

| 场景 | 处理 |
|---|---|
| 流式输出中 | 光标闪烁，自动滚到底；用户手动上滚后**停止自动滚动** |
| 工具执行中 | 卡片显示 loading + 已耗时；超过超时阈值显示"可能较慢" |
| 审批 | 卡片置顶 + 页面 title 变化 + 声音提示（可关）；不能滚动走 |
| 中断 | 发送按钮变"停止"，点击后 abort + 发 `ABORT`，保留已收到内容 |
| 失败 | 显示 `error_code` 对应的人话 + "重试"按钮（重试用原 client_msg_id 新建 run） |
| 断线 | 顶部条"连接已断开，正在恢复"，自动重连 + 补拉 |
| 引用 | 角标 hover 显示片段，点击跳原文并高亮 |
| 长会话 | 消息虚拟滚动；事件时间线按需折叠（默认收起中间步骤） |

## 7. 性能

| 风险 | 措施 |
|---|---|
| 流式高频 setState | 用 `requestAnimationFrame` 批量合并 delta（每帧一次） |
| 长会话 DOM 爆炸 | TanStack Virtual 虚拟滚动 |
| 事件数组无限增长 | 中间步骤默认折叠，只保留最近 N 条展开态 |
| Markdown 重复解析 | 只在 `message.completed` 或每 100ms 节流解析一次 |

> 你简历里"1 万点位迁 Web Worker"的经验在这里可以复用叙事：**瓶颈通常在数据处理而非渲染**，同样的判断方法适用。

## 8. 类型同源

```
Pydantic 模型 ──► OpenAPI ──► openapi-typescript ──► src/api/generated.ts
```

- 后端改接口 → `pnpm gen:api` → 前端类型自动更新
- 事件 payload 也用 Pydantic 定义，前端生成对应类型
- **禁止手写重复的接口类型**

## 9. 可访问性与国际化

- 对话区域 `aria-live="polite"`，流式完成时整体播报一次（不是每个 delta）
- 审批按钮有明确 `aria-label`，键盘可达
- i18n 只做 zh-CN（v1 不引入 i18n 框架，文案集中在一个 `text.ts`，避免散落）

## 10. 前端验收清单

- [ ] 断网 10 秒再恢复，消息不丢不重
- [ ] 审批卡出现时，刷新页面能恢复（从事件补拉重建）
- [ ] 点中断后，已收到内容保留，且不再有新事件
- [ ] 未知事件类型不崩溃
- [ ] 1000 条消息的会话滚动流畅
- [ ] 引用角标能跳到正确原文位置
