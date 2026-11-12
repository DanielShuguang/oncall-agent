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

> W4 已落地 `/runs`、`/runs/:id` 与 `/console/cost`：运行详情用 `runtimeReducer`
> 重放事件重建步骤/工具/消息，不重新执行 Agent；成本页按 day/model/user 分组，
> 直接调用 `/admin/cost/summary`。导航从「对话」扩展为 对话 / 运行 / 管理后台。
> 事件过了保留期（默认 180 天，ADR-0021）会被整场清理：详情页用 `events_pruned_at`
> 显示「事件已过保留期被清理」，时间线与工具调用标为不可用，摘要/计量/失败归因与最终回答（`run.output`）照常展示，引用角标退化为不可用。
> 回答引用的文档按当前可见性回收（ADR-0022）时，详情页用 `content_redacted` 显示
> 「引用的文档已不可见」并隐藏回答与回放（`output` 为 null、事件为空），`input`/摘要/计量照常；
> 提示里写明"可见范围恢复后内容自动恢复"，不要把它画成失败或已删除。
> 正文过了保留期（ADR-0023）时详情页用 `content_pruned_at` 显示「正文已过保留期，已清空」，
> 问题与回答都不再展示（`input` 是空串、`output` 为 null），只留摘要/计量/失败归因；
> 这种删除**不可恢复**，提示里不能写「恢复可见范围后内容自动恢复」——那是 ADR-0022 的语义。
>
> W5 已落地 `/console/kb`、`/console/tools`、`/console/perms`、`/console/approvals`：
> 这些页面与成本页都按路由懒加载，表格在小屏横向滚动。D25 的 iframe 嵌入形态**未做**：
> 它需要 `postMessage` 来源白名单与 CSP `frame-ancestors` 的部署决策，先不引入
> 一个说不清边界的外嵌入口。

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

token 来源：v1 没有登录页，token 存在 `localStorage.oncall.token`，右上角「设置 Token」粘贴
（签发见 docs/11 §2.1）；`api/client.ts` 的 `authHeaders()` 统一注入，换 SSO 时只改这里。

## 5. 组件树

```
ChatPage
|-- SessionList            会话侧栏：新会话 + 最近会话 + 加载更多，点击回看并继续（ADR-0030/0033）
├─ MessageList             直接渲染（未做虚拟滚动）
│  ├─ UserMessage
│  ├─ AssistantMessage
│  │  ├─ MarkdownText      流式中渲染，代码块/表格
│  │  └─ CitationList      角标 [1][2]，点击跳原文
│  │     └─ CitationPreviewDialog 全文按切片重组 + 引用段高亮（ADR-0018）
│  ├─ StepTimeline         step.started/completed
│  ├─ ToolCard             tool.call/result：参数、状态、耗时、错误
│  └─ ApprovalCard         approval.required
│     ├─ ArgsPreview       参数人类可读化（不是裸 JSON）
│     ├─ RiskBadge         风险等级
│     └─ Actions           批准 / 拒绝 / 本会话允许
├─ Composer                输入框，Enter 发送，Shift+Enter 换行
└─ ConnectionBanner        断线提示 + "正在恢复…"
```

> 已实现会话列表（ADR-0030）：左侧列出最近会话，点开可回看只读 transcript 并继续对话；
> 列表底部可「加载更多会话」，消息区顶部可「加载更早的对话」（keyset 游标，ADR-0033）。
> 历史回答的引用角标按快照还原、仍可点开全文预览（ADR-0031），但工具与审批卡片不回放。
> 窄屏（<640px）暂隐藏会话栏（尚无抽屉入口），刷新后不自动恢复上次会话。
> 仍未做消息虚拟滚动，长会话直接渲染（后续可加）。

通用样式原语（Button / Tag / Card / Alert / Tabs）在 `src/components/ui.tsx`，页面只做组合，不重复写按钮/标签样式（见 §11）。

管理后台：

```
ConsolePage（Tabs，路径 /console/:panel）
├─ KbPage         上传（含可见范围）、列表、切片预览、改可见范围、重建索引
├─ ToolsPage      工具卡片、Schema 查看（只读）、启用开关、试调用
├─ PermsPage      角色 × 工具矩阵（勾选即保存）
├─ ApprovalsPage  待办/已办可筛，逐条决议（理由 + 授权范围）
└─ CostPage       日/模型/用户三段聚合 + 趋势图 + Top 花费 run + 个人日预算配置与今日账本用量（ADR-0026/0028）
```

## 6. 交互细节（这些才是"体验"）

| 场景 | 处理 |
|---|---|
| 流式输出中 | 光标闪烁，自动滚到底；用户手动上滚后**停止自动滚动** |
| 工具执行中 | 卡片显示 loading + 已耗时；超过超时阈值显示"可能较慢" |
| 审批 | 卡片置顶 + 页面 title 变化 + 声音提示（可关）；不能滚动走 |
| 中断 | 发送按钮变"停止"，点击后 abort + 发 `ABORT`，保留已收到内容 |
| 失败 | 显示 `error_code` 对应的人话 + "重试"按钮；重试会移除失败气泡、用**新的** `client_msg_id` 重发（原 id 会命中幂等回放，拿回同一条失败 run） |
| 断线 | 顶部条"连接已断开，正在恢复"，自动重连 + 补拉 |
| 引用 | 角标 hover 显示片段；点击打开 Dialog：按切片顺序展示全文、引用段高亮并滚到视野中央（`chunk_id` 优先、`ord` 兜底），加载失败退回片段并说明「不是全文」；只有登录要求，与检索同一可见性（[ADR-0018](decisions/0018-citation-fulltext-preview.md)）。受限文档返回 404，前端走同一个「文档不存在或已更新」兜底，不区分「无权限」与「没这篇」（[ADR-0019](decisions/0019-document-level-access.md)） |
| 长会话 | 消息虚拟滚动；事件时间线按需折叠（默认收起中间步骤） |
| 多轮 | `session_id` 是一段对话的上下文作用域：`reset()`（新会话）生成新的 ID，否则新会话的第一句会带着上一段的上下文（[ADR-0020](decisions/0020-multi-turn-context.md)）。刷新页面会开一个当前会话，**历史在左侧列表**，点开即可回看并沿用同一个 `session_id` 继续；v1 不自动恢复最后一次会话。后端按「用户 + session」取最近 3 轮，客户端不传历史 |

### 6.1 断线续传的实现（W1 D4）

- `streamChat` 抛错且已收到 `run.started`（有 `runId`）时，不直接判失败：按
  `lastSeq` 调 `GET /runs/{id}/events?after_seq=`，只应用 `seq > lastSeq` 的事件
- `run_status == "running"` → 每秒轮询，最长 2 分钟；`awaiting_approval` / 终态立即停止
- 用户主动 `abort` 不触发补拉；补拉是**重放**而不是增量猜测，UI 仍由归约器重建
- 事件必须按 `seq` 幂等应用：重复帧、补拉与实时流交错都不能产生重复卡片
- 服务端空闲每 15s 发 `: heartbeat`；幂等 replay 遇到 `running` 会继续跟到终态（上限 5 分钟）

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
- [x] 审批卡可提交（W3 D14）：批准/拒绝走 `POST /approvals/{id}/resolve`，随后轮询事件到终态
- [ ] 点中断后，已收到内容保留，且不再有新事件
- [ ] 未知事件类型不崩溃
- [x] 任意历史 run 可按 seq 回放（W4 D20）：`/runs/:id` 拉全量事件后走同一个 reducer
- [x] 超过保留期的 run 显示「事件已清理」，不把空时间线伪装成没有步骤（W6 后补，ADR-0021）
- [x] 引用文档收权后，详情页隐藏回答与回放并标明原因，不画成失败（W6 后补，ADR-0022）
- [x] 正文过保留期后详情页只留摘要，标明「已清空且不可恢复」，与「不可见」区分（W6 后补，ADR-0023）
- [x] 成本看板与 `model_calls` 对得上（W4 D19）：`/console/cost` 展示分/调用/token
- [x] 不写代码能上传文档、看切片、重建索引（W5 D21）
- [x] 不写代码能设「公开 / 指定角色」，列表显示可见范围且不重切就能改（W6 后补，ADR-0019）
- [x] 受限文档在员工侧检索不到、引用跳全文 404，管理员仍可读（同一规则两处实现）
- [x] 工具试调用走治理链路，写工具不会真的落单（W5 D22）
- [x] 权限矩阵可编辑、审批中心待办/已办可筛（W5 D23）
- [x] 失败后重试不重复用户气泡，且改用新的 `client_msg_id`（W5 D24）
- [ ] iframe + postMessage 嵌入形态（W5 D25，暂缓，见 §2 说明）
- [ ] 运行列表在 10 万条 run 下的分页体验（当前游标分页，未压测）
- [ ] 1000 条消息的会话滚动流畅
- [x] 引用角标能跳到正确原文位置（W5 D24 收尾）：引用段高亮并自动滚动，失效引用不假装定位

## 11. 样式系统与代码约束

### 11.1 Tailwind CSS 4

- 接入方式：`@tailwindcss/vite` 插件（`vite.config.ts`），**不用** PostCSS 配置
- 唯一入口：`src/styles/global.css` 里 `@import 'tailwindcss'`
- 设计令牌：全部写在 `@theme` 里，Tailwind 会生成对应 utility
  （`--color-panel` → `bg-panel`，`--color-muted-fg` → `text-muted-foreground`）

| 令牌 | utility | 用途 |
|---|---|---|
| `--color-canvas` | `bg-canvas` | 页面底色 |
| `--color-panel` | `bg-panel` | 卡片 / 输入框底色 |
| `--color-line` | `border-line` | 分隔线与边框 |
| `--color-ink` | `text-ink` | 正文 |
| `--color-muted` | `bg-muted` | 弱背景（shadcn `--muted`） |
| `--color-muted-fg` | `text-muted-foreground` | 次要信息文字 |
| `--color-brand` | `text-brand` / `bg-brand` | 主色 |
| `--color-ok` / `--color-warn` / `--color-danger` | `text-ok` … | 状态语义 |

约定：

- 组件里**只有** utility class，不写内联 `style`、不新增 `.oncall-xxx` 全局类
- 条件样式用 `cn()`（shadcn 官方的 `cn` 包，即编译版 clsx + tailwind-merge）拼接
- 通用组件用 shadcn（见 §11.3），业务组件不重复实现按钮 / 标签 / 卡片

> 为什么不用运行时组件库：antd 的 CSS-in-JS 与 Tailwind 的 preflight 会互相覆盖，样式优先级要靠加载顺序
> 去赌，排障成本远高于「复制源码 + 令牌映射」。取舍记录见 [decisions/0006](decisions/0006-tailwind-and-oxc.md)。

### 11.3 组件层：shadcn/ui（源码复制）

- 配置：`web/components.json`（`style: new-york`、`baseColor: neutral`、`css: src/styles/global.css`、`rsc: false`）
- 添加组件：`pnpm dlx shadcn@latest add <name>`，输出到 `src/components/ui/`
- **只加用得到的组件**，不要 `add --all`；当前已加：button / badge / card / alert / tabs / textarea / input / label / separator / table / dialog / dropdown-menu / select / tooltip（后八个为 W5 后台预置，未 import 不进产物）
- 交互与 a11y 由 `radix-ui` 提供（Dialog 焦点陷阱、Select 键盘导航、Table 语义），样式仍由 Tailwind 决定
- `TooltipProvider` 只在 `src/main.tsx` 挂一次

颜色映射（**只此一处**，组件里不写色值）：

| shadcn 令牌 | 映射到 |
|---|---|
| `--background` / `--card` / `--popover` | `--color-panel` |
| `--foreground` | `--color-ink` |
| `--primary` / `--ring` | `--color-brand` |
| `--muted-foreground` | `--color-muted-fg` |
| `--destructive` | `--color-danger` |
| `--border` / `--input` | `--color-line` |

页面底色仍是 `--color-canvas`（`bg-canvas`，body 设置），`--background` 指「面板白」，不要混用。

### 11.4 代码约束（oxc）

| 工具 | 命令 | 配置 |
|---|---|---|
| `oxlint` | `pnpm lint` / `pnpm lint:fix` | `web/.oxlintrc.json` |
| `oxfmt` | `pnpm format` / `pnpm format:check` | `web/.oxfmtrc.json` |

- 规则集：`correctness` 报错、`suspicious` 与 `perf` 告警；插件开 react / jsx-a11y / typescript / unicorn / import / promise / vitest
- 行宽 100、单引号，与 `.editorconfig` 一致
- 与后端的分工不变：oxc 只管 JS/TS/JSON/Markdown 的格式与静态检查，类型仍由 `tsc --noEmit` 把关
- **Biome 已移除**，不要混用两套格式化器（会让 diff 来回震荡）
