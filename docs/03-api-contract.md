# 03 · API 契约

> **这是前后端唯一的契约文件。** 改接口先改这里，再改代码。类型由 Pydantic 导出 OpenAPI，前端 `openapi-typescript` 生成，禁止手写重复类型。

Base：`/api`　鉴权：`Authorization: Bearer <token>`（v1 用本地签发的 JWT，不接 SSO）

## 0. 鉴权

除 `GET /health` 与 OpenAPI 文档（`/openapi.json`、`/docs`、`/redoc`）外，
所有**业务接口**都要求 Bearer token（ADR-0010）。

- 签发（运维侧、不经过 HTTP）：

  ```bash
  cd server
  uv run python -m app.cli token --user u_102 --roles employee
  # --roles 逗号分隔；--ttl-minutes 默认 480（8 小时）
  ```

- claims：`sub`（user_id）、`roles`、`iat`、`exp`；HS256，密钥 `ONCALL_SESSION_SECRET`
- 失败：`401 {"code":"UNAUTHORIZED","message":"缺少或无效的 token"}` + `WWW-Authenticate: Bearer`，**不建 SSE**
- 归属：只能访问自己的 run；别人的 run 返回 `404`（不用 403，避免泄露 run 是否存在）
- 前端：没有登录页，token 存在 `localStorage.oncall.token`，对话框入口在右上角「设置 Token」；接 SSO 时替换 `api/deps.get_identity` 与前端 token 获取（`api/client.ts`）
- 管理接口（`/api/admin/kb/*`、`/api/admin/tools/*`、`/api/admin/perm-matrix`、`/api/admin/cost/*`、`/api/admin/budgets/*`）额外要求 `ONCALL_ADMIN_ROLES` 中的任一角色（默认 `admin`）；不满足返回 `403 {"code":"FORBIDDEN","message":"需要管理员角色"}`。工具/角色矩阵的覆盖存 `tool_settings`（ADR-0014），按用户日预算的覆盖存 `user_budgets`（ADR-0026）。
- 例外是引用跳全文 `GET /api/kb/documents/{id}/preview`：它属于对话链路而不是管理面，只要求登录（与检索同一可见性，ADR-0018）。

## 1. 接口清单

| 方法 | 路径 | 说明 | 阶段 |
|---|---|---|---|
| GET | `/health` | 健康检查（含 db/redis 探活） | W1 D1 |
| POST | `/chat/stream` | 发起一次对话，返回 SSE 流 | W1 D3 |
| GET | `/runs` | 运行列表（分页、按状态/会话筛选） | W4 D19 / W6 后补 |
| GET | `/sessions` | 当前用户的会话列表（keyset 游标，按活动倒序；可选 `q` 按标题搜索） | W6 后补 |
| PATCH | `/sessions/{session_id}` | 改会话显示标题；`title: null` 恢复默认 | W6 后补 |
| DELETE | `/sessions/{session_id}` | 从会话列表移除（软移除；不删 run/事件/审批，204） | W6 后补 |
| GET | `/sessions/hidden` | 本人从列表移除的会话（游标分页 + 标题搜索，ADR-0043/0047） | W6 后补 |
| DELETE | `/sessions/{session_id}/hidden` | 恢复已移除的会话（只删 `hidden_sessions` 行，204） | W6 后补 |
| POST | `/sessions/hidden/restore` | 批量恢复已移除会话（最多 50，部分成功，返回逐条结果） | W6 后补 |
| GET | `/sessions/{session_id}/runs` | 一页会话详情（正文/引用/运行过程，一次返回） | W6 后补 |
| GET | `/runs/{run_id}` | 单次运行详情（含指标与模型调用明细） | W1 D4 / W4 D19 |
| GET | `/runs/{run_id}/events?after_seq=` | 补拉事件（断线续传，兼容 `Last-Event-ID`） | W1 D4 |
| GET | `/runs/{run_id}/stream` | 重连增量流（可选，v1 用轮询替代） | — |
| POST | `/approvals/{id}/resolve` | 审批通过/拒绝 | W3 D14 |
| GET | `/approvals?status=pending&limit=50` | 待办/已办审批列表（keyset 游标分页；第一页附总数；已办可加 `tool/resolved_by/resolved_from/resolved_to` 筛选） | W3 D14 / W5 D23 / W6 后补 |
| GET | `/approvals/export?status=approved&tool=create_ticket` | 按当前状态/筛选导出审批 CSV（最多 5000 条；响应头告知截断） | W6 后补 |
| GET | `/approvals/stats?days=7&group_by=` | 审批积压、窗口内等待与按工具/审批人分组（仅审批人） | W6 后补 |
| POST | `/admin/kb/documents` | 上传知识文档（multipart，≤10MB） | W2 D7 |
| GET | `/admin/kb/documents` | 知识库文档列表 + chunk 总数 | W2 D7 |
| GET | `/admin/kb/documents/{id}?preview=20` | 文档详情与切片预览（含 heading_path） | W2 D7 |
| PATCH | `/admin/kb/documents/{id}/access` | 改文档可见范围（不重切，`chunk_id` 不变） | W6 后补 |
| GET | `/kb/documents/{id}/preview?chunk_id=&ord=` | 引用跳全文（登录即可；受文档可见性约束，不可见 404） | W5 D24 |
| POST | `/admin/kb/reindex` | 重建索引（用当前 embedder 重算向量） | W2 D8 |
| GET | `/admin/tools` | 工具注册表（含生效角色/启用状态） | W3 D12 / W5 D22 |
| PATCH | `/admin/tools/{name}` | 启用/禁用工具（`enabled: null` 恢复默认） | W5 D22 |
| GET | `/admin/tools/{name}/history` | 工具配置变更历史（谁在何时把启用/角色改成什么） | W6 后补 |
| POST | `/admin/tools/{name}/test` | 工具试调用（强制走治理链路） | W5 D22 |
| GET | `/admin/perm-matrix` | 角色 × 工具矩阵 | W3 D12 / W5 D23 |
| PUT | `/admin/perm-matrix` | 更新矩阵（按工具部分更新） | W5 D23 |
| GET | `/admin/cost/summary?from=&to=&group_by=day\|model\|user` | 成本聚合 | W4 D19 |
| GET | `/admin/budgets` | 个人日预算默认值 + 覆盖列表 | W6 后补 |
| PUT | `/admin/budgets/{user_id}` | 设置/更新某用户的日预算 | W6 后补 |
| DELETE | `/admin/budgets/{user_id}` | 删除覆盖、回到默认值（204） | W6 后补 |
| GET | `/admin/budgets/usage` | 今日账本用量（已用、未结算预扣、卡住笔数） | W6 后补 |
| GET | `/admin/eval/report?batch_id=` | 评测报告 | W6 D26 |

## 2. 对话流

### 2.1 请求

```http
POST /api/chat/stream
Content-Type: application/json
Authorization: Bearer <token>
Accept: text/event-stream

{
  "session_id": "sess_01H...",
  "client_msg_id": "cmsg_8f2a...",
  "message": "我电脑连不上打印机了",
  "options": { "model": null, "max_steps": 12 }
}
```

- `client_msg_id` 是**幂等键**：同一用户重复提交返回同一个 `run_id`，不重复执行；空字符串按“未提供”处理
- `session_id` 是**多轮上下文的作用域**：服务端按「当前用户 + `session_id`」取最近 3 轮已结束且有回答的
  run（`runs.input/output`），把问答对作为 `messages` 注入本轮状态（[ADR-0020](decisions/0020-multi-turn-context.md)）；
  正文已被保留策略清空的轮次（[ADR-0023](decisions/0023-run-content-retention.md)）不进历史。
  历史只用于理解指代（「那怎么办」「它需要审批吗」），**不是证据**：`citations` 仍只能来自本轮检索。
  客户端不传历史、也不能改历史；前端「清空对话」必须换一个新的 `session_id`，否则新会话会带着上一段上下文
- `options.model` 为空时由网关规则选模型（mock 模式是 `rule-engine`）；非空时只在**已配置的模型**
  之间路由，未知模型名忽略（避免客户端指定任意模型）
- 限流：`ONCALL_RATE_LIMIT_PER_MIN`（默认 30 次/分钟/用户，0 关闭）。超限在**建 run 之前**
  返回 `429 {"code":"RATE_LIMITED"}` + `Retry-After: 60`，不建 SSE、不产生 run；
  同一 `client_msg_id` 的幂等重放即使额度耗尽也走回放，不会因为一次网络重试被 429 挡住
- 幂等命中时服务端只**回放已落库事件**（可带 `Last-Event-ID` 从断点开始），不会再跑一遍 Agent；若该 run 仍在 `running`，服务端继续跟到终态并用心跳保活（上限 5 分钟），客户端也可改用 `/runs/{run_id}/events` 轮询补齐
- 响应头：`Content-Type: text/event-stream; charset=utf-8`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`（Nginx 不缓冲）

### 2.2 SSE 帧格式

```
id: 7
event: tool.call
data: {"seq":7,"run_id":"01J...","type":"tool.call","ts":"2026-11-09T02:11:03.120Z","payload":{"call_id":"call_1","tool":"search_kb","args":{"query":"打印机 离线"},"write":false}}

```

- `id` = `seq`，前端存下来用于续传
- `event` = 事件类型（下方枚举）
- `data` = 完整事件对象（一行，无换行）
- 每 15s 发送 `: heartbeat` 注释行保活（不占 `seq`）

### 2.3 事件类型

| type | payload | 前端动作 |
|---|---|---|
| `run.started` | `{run_id, model, max_steps}` | 建 run 卡片，置 running |
| `step.started` | `{step, node, title}` | 步骤条新增"进行中" |
| `step.completed` | `{step, node, duration_ms, summary}` | 步骤条完成 |
| `tool.call` | `{call_id, tool, args, write:boolean}` | 渲染工具卡片（参数） |
| `tool.result` | `{call_id, status:"ok"\|"error"\|"timeout"\|"denied"\|"requires_approval", result, duration_ms, error, approval?}` | 工具卡片填充结果/错误 |
| `approval.required` | `{approval_id, tool, args, risk_level, expires_at, reason}` | 弹审批卡，state→awaiting_approval |
| `approval.resolved` | `{approval_id, status:"approved"\|"rejected"\|"expired", resolved_by, reason, scope}` | 审批卡置终态；`rejected/expired` 后紧跟一条 `run.failed` |
| `message.delta` | `{text}` | 追加到当前消息气泡 |
| `message.completed` | `{text, citations:[{chunk_id,document_id,ord,title,heading,snippet,page}]}` | 收尾，渲染引用角标；点击打开原文片段 |
| `run.completed` | `{status, steps, token_in, token_out, cost_cents, duration_ms}` | 置 completed，显示成本；`duration_ms` 是本次执行段耗时，审批等待不计入 |
| `run.failed` | `{error_code, message, at_step, category}` | 置 failed，显示重试；`category` 是 model/tool/approval/limit/internal 归因 |
| `heartbeat` | — | 忽略（或用于探测超时） |

> W1 没有 LLM 调用：`run.started.model` 默认是 `rule-engine`；W4 网关接入后，mock 模式仍是
> `rule-engine`（确定性规则、成本 0），真实模式是 plan 的首选模型名，单次调用实际走了哪个
> provider 看 `model_calls`（`GET /runs/{id}`）。
> W2 的 `retrieve` 是**节点**而不是工具，所以只发 `step.*`，不发 `tool.call`；
> `message.completed.citations` 为本次实际用到的 1-3 条（无命中时为空数组）。
> W3 的节点顺序固定为 `intake → classify → retrieve → plan → act → verify → finalize`；
> 写操作在 `act` 挂起，run 停在 `awaiting_approval`，审批通过后从 `approve → act → verify → finalize` 继续。
> OpenAPI 已声明 `BearerAuth` 安全方案（`fastapi.security.HTTPBearer`），Swagger 可直接 Authorize。

### 2.4 错误语义（三种，不要混）

| 情况 | HTTP/事件 | 前端表现 |
|---|---|---|
| 请求本身不合法（未鉴权、字段缺失） | `4xx` JSON `{code,message}`（401 见 §0；422 是 FastAPI 校验格式），**不建 SSE** | 表单报错 / 提示设置 Token |
| 请求限流 | `429 {"code":"RATE_LIMITED"}` + `Retry-After: 60`，**不建 SSE** | 提示稍后再试 |
| 管理接口无权限 | `403 {"code":"FORBIDDEN","message":"需要管理员角色"}` | 提示切换有 admin 角色的 Token |
| 幂等命中的 run 回答已回收 | `403 {"code":"CONTENT_REDACTED"}`，**不建 SSE**（[ADR-0022](decisions/0022-run-content-visibility.md)） | 不重试；打开运行详情看回收标记 |
| 幂等命中的 run 正文已过保留期 | `410 {"code":"CONTENT_EXPIRED"}`，**不建 SSE**（[ADR-0023](decisions/0023-run-content-retention.md)） | 不重试；正文已按保留策略清空 |
| 数据库不可用（建流前落库失败） | `503` JSON `{detail}` | 提示稍后重试，不要进入"假运行" |
| 运行期失败（模型超时、工具全挂） | `200` + `run.failed` 事件 | 卡片显示失败 + 重试按钮 |
| 连接断开 | 无 | 用 `lastEventId` 补拉 |

> 规则：**能建流就 200**。别用 500 表达"模型挂了"，那是运行期失败，前端要能展示部分结果。

## 3. 断线续传

```http
GET /api/runs/{run_id}/events?after_seq=7&limit=200
Last-Event-ID: 7
```

```json
{ "events": [ ... ], "next_seq": 42, "run_status": "running", "content_redacted": false }
```

- `after_seq` 与 `Last-Event-ID` 都支持：**查询参数优先**；两者都没传按 0 处理；非法 header 也按 0（不因续传参数把主流程打成 422）
- `limit` 默认 200、上限 500；`next_seq` 是本次返回的最后一个 `seq`（没有新事件时等于请求的起点）
- run 不存在返回 `404`，不要用空数组掩盖
- 事件超过保留期（默认 180 天）会被**按 run 整场清理**（[ADR-0021](decisions/0021-data-retention.md)）：
  此时仍返回 `200` + `events: []`（run 没消失，`run_status` 仍可读）；要区分"没有事件"和
  "清理过"，看 `GET /runs/{run_id}` 的 `events_pruned_at`
- 回答引用的文档已不可见（可见范围被改窄/文档被删除）时，事件整场不回放（[ADR-0022](decisions/0022-run-content-visibility.md)）：
  同样 `200` + `events: []`，但 `content_redacted: true`；原因与处理看详情的同名标记
- 正文过保留期（[ADR-0023](decisions/0023-run-content-retention.md)）时事件早已按 ADR-0021 清掉，
  同样是 `200` + `events: []`，且 `content_redacted: false`：正文已经不存在，不属于权限回收。
  与详情同一口径（是否过期看 `content_pruned_at`）；字段形态不变（R1：只增不改）

### 3.1 运行列表

```http
GET /api/runs?limit=20&status=failed&cursor=<opaque>&session_id=sess_01H...
Authorization: Bearer <token>
```

```json
{
  "items": [
    {
      "run_id": "9a17...",
      "status": "failed",
      "user_id": "u_102",
      "session_id": "sess_01H...",
      "intent": "ticket_create",
      "model": "qwen2.5:7b",
      "step_count": 5,
      "max_steps": 12,
      "token_in": 900,
      "token_out": 120,
      "cost_cents": 2,
      "error_code": "TOOL_ERROR",
      "failure_category": "tool",
      "event_count": 18,
      "events_pruned_at": null,
      "content_pruned_at": null,
      "started_at": "2026-11-09T02:11:03.120Z",
      "finished_at": "2026-11-09T02:11:04.400Z"
    }
  ],
  "next_cursor": "MjAyNi0xMS0wOVQwMjoxMTowMy4xMjArMDB8OWExNw=="
}
```

- 只返回当前用户的 run；`status` 可选，值同事件流状态
- `session_id` 可选，按会话过滤（仍只查自己的；会话列表见 3.3）。打开历史会话时用它取最近
  20 条 run，再逐条取详情拼只读 transcript；更早的轮次用 `cursor` 继续翻（ADR-0033）
- `limit` 默认 20、上限 100；`next_cursor` 为 `null` 表示没有下一页
- `cursor` 是不透明字符串（base64 的 `started_at|run_id`）；非法 cursor 返回
  `400 {"code":"INVALID_CURSOR"}`，不要静默从头开始
- `failure_category` 只对失败 run 有值，用来回答「失败在模型、工具、审批还是护栏」
- `events_pruned_at` 非空表示事件已按保留策略清理（ADR-0021）：`event_count` 是
  当前仍保留的条数（清理后为 0），回放不可用，摘要与 `output` 仍可信
- `content_pruned_at` 非空表示正文（`input`/`output`）已按保留策略清空（ADR-0023）：
  列表不返回正文，这个标记只是让详情/前端能解释「为什么没有内容」

### 3.2 单次运行详情

```http
GET /api/runs/{run_id}
```

```json
{
  "run_id": "9a17959c-6ee7-4015-bf2d-addc2c79f168",
  "status": "completed",
  "user_id": "u_102",
  "session_id": "sess_01H...",
  "intent": "asset_check",
  "model": "qwen2.5:7b",
  "step_count": 6,
  "max_steps": 12,
  "token_in": 1820,
  "token_out": 310,
  "cost_cents": 3,
  "error_code": null,
  "failure_category": null,
  "event_count": 23,
  "events_pruned_at": null,
  "content_pruned_at": null,
  "started_at": "2026-11-09T02:11:03.120Z",
  "finished_at": "2026-11-09T02:11:04.400Z",
  "input": "我电脑连不上打印机了",
  "output": "你名下的笔记本…",
  "content_redacted": false,
  "citations": [
    {
      "chunk_id": 1024,
      "document_id": "doc_payroll",
      "ord": 0,
      "title": "薪酬制度",
      "heading": "3.2 报销",
      "snippet": "报销需在事项发生后 30 天内提交…",
      "page": 3
    }
  ],
  "timeline": [
    {
      "kind": "tool",
      "seq": 12,
      "call_id": "call_1",
      "tool": "query_cmdb",
      "args": {},
      "write": false,
      "status": "ok",
      "result": {"assets": [{"asset_id": "PC-20481", "model": "ThinkPad T14"}], "count": 1},
      "duration_ms": 3,
      "attempts": 1
    },
    {
      "kind": "approval",
      "seq": 18,
      "approval_id": "apr_1",
      "tool": "create_ticket",
      "args": {"title": "打印机报修"},
      "risk_level": "high",
      "reason": "将创建工单",
      "status": "approved",
      "requested_at": "2026-11-09T02:05:31.000Z",
      "resolved_at": "2026-11-09T02:11:04.100Z",
      "waited_ms": 333100,
      "decision_reason": "确认报修"
    }
  ],
  "timeline_available": true,
  "timeline_truncated": false,
  "model_calls": [
    {
      "step": "plan",
      "provider": "local",
      "model": "qwen2.5:7b",
      "token_in": 1820,
      "token_out": 310,
      "cost_cents": 3,
      "latency_ms": 840,
      "first_token_ms": null,
      "status": "ok",
      "error": null,
      "created_at": "2026-11-09T02:11:03.900Z"
    }
  ]
}
```

前端合并策略：

1. 断线 → 记住 `lastEventId`
2. 重连 → 先 `GET /events?after_seq=lastEventId` 补齐
3. 若 `run_status == "running"` 且支持 `/stream`，再挂增量流；否则轮询到终态
4. **以事件重放重建 UI，不做增量猜测**（避免"补拉 + 实时"交错导致重复渲染）

> `content_redacted`（[ADR-0022](decisions/0022-run-content-visibility.md)）：回答引用的知识库
> 文档按**读取时**的角色重新校验，任何一篇不可见（改窄或删除）就整场回收——`output: null`、
> 事件不回放、多轮历史剔除该轮；`input`、状态、计量、失败归因照常。回收不改存储，可见范围
> 改回去后自动恢复。列表接口不返回 `output`，所以不带这个字段。
>
> `content_pruned_at`（[ADR-0023](decisions/0023-run-content-retention.md)）：正文过保留期后
> `input` 返回**空串**、`output` 返回 `null`，状态/计量/失败归因/`events_pruned_at` 照常；
> 此时 `content_redacted` 恒为 `false`——内容已经不存在，不属于「按你的权限隐藏」，
> 两种原因同时成立时以过期为准。空串不会与正常输入混淆：`message` 的最小长度是 1。
>
> `citations`（[ADR-0031](decisions/0031-run-citations-replay.md)）：`message.completed`
> 里引用快照的投影，供历史会话还原角标。只在 `output` 可见且正文未过期时返回；
> `output` 缺失、`content_redacted` 或 `content_pruned_at` 非空时恒为 `[]`——引用片段
> 是回答内容，不能比正文活得久。预览仍走 `/kb/preview`，按**当前**权限校验；列表接口不返回它。
>
> `timeline`（[ADR-0035](decisions/0035-run-timeline-replay.md)）：历史回答的只读运行过程，
> 由 `tool.call` / `tool.result` / `approval.required` / `approval.resolved` 事件投影而来；
> 按 `call_id`、`approval_id` 合并，步骤与 `message.delta` 不进入。最多 20 项，超出时
> `timeline_truncated: true`。与 `citations` 一样只在回答可见时返回：`output` 缺失、
> `content_redacted`、`events_pruned_at` 或 `content_pruned_at` 非空时 `timeline: []` 且
> `timeline_available: false`——「过程不可用」不能显示成「这轮没有调用工具」。
> 单个 `args` / `result` 的紧凑 JSON 超过 4096 字符时，只返回
> `{"truncated": true, "original_chars": N, "preview": "<前 1024 字符>"}`；
> 工具 `error` 超过 4096 字符时截到 1024 字符并追加「…（原始 N 字符，已截断）」。
> 该条目带 `truncated: true`；事件中的原始载荷不变（[ADR-0044](decisions/0044-timeline-payload-cap.md)）。
> 审批项带 `requested_at`（发起事件时间）与 `waited_ms`（发起到决议的毫秒数，仅已决议项有；
> 决议早于发起的脏数据省略该字段），用于区分工具执行耗时与人工等待
> （[ADR-0046](decisions/0046-approval-wait.md)）。等待时长不进入工具耗时汇总。
> 为保护内部治理信息，审批卡不返回 `resolved_by` 与 `scope`。列表接口不返回这些字段；
> 历史过程只读，不提供重试/批准/拒绝。

### 3.3 会话列表（ADR-0030 / ADR-0033 / ADR-0039 / ADR-0040）

```http
GET /api/sessions?limit=20
Authorization: Bearer <token>
```

```json
{
  "items": [
    {
      "session_id": "sess_01H...",
      "title": "我电脑连不上打印机了",
      "run_count": 3,
      "started_at": "2026-11-09T02:11:03.120Z",
      "updated_at": "2026-11-09T02:26:41.008Z"
    }
  ],
  "next_cursor": "eyJ0IjoiMjAyNi0xMS0wOVQwMjoyNjo0MS4wMDgrMDA6MDAiLCJzIjoic2Vzc18wMUgifQ=="
}
```

翻下一页时把上一页的 `next_cursor` 原样带回：

```http
GET /api/sessions?limit=20&cursor=eyJ0IjoiMjAyNi0xMS0wOVQwMjoyNjo0MS4wMDgrMDA6MDAiLCJzIjoic2Vzc18wMUgifQ==
```

按标题搜索时加 `q`（1–100 字符，大小写不敏感子串，只搜本人）：

```http
GET /api/sessions?limit=20&q=打印机
```

- 会话不是独立实体：按 `runs.session_id` 聚合投影，没有 `sessions` 生命周期表；
  用户改过的显示标题存在旁挂的 `session_titles`（ADR-0040，迁移 `0016`），
  没有 run 的会话不存在，不需要清理任务
- 只返回当前用户的会话；按 `updated_at`（最近一次 run 的 `started_at`）倒序，
  同一时刻按 `session_id` 倒序，避免顺序抖动
- `title` 优先取自定义标题（ADR-0040），否则取**最早一条非空 `input`**，压成单行并截到
  60 字符；正文按 ADR-0023 过期清空且没改过名时为 `null`，前端显示「无标题」，
  **会话本身仍会返回**（不能因为标题没了就藏掉历史）
- `limit` 默认 20、上限 50；`next_cursor` 是 keyset 游标，当前页取满就会返回；
  下一页没有数据时返回空列表且 `next_cursor` 为 `null`（恰好取满时会多一次空请求）。
  游标对前端不透明（base64url JSON，带 `updated_at` 与 `session_id`，最多 512 字符），
  非法游标返回 `400 {"code":"INVALID_CURSOR"}`，不要静默从头开始
- 游标不签名：伪造游标只能改变自己的起点，不会越权读到别人的会话（ADR-0033）
- `q` 同时匹配自定义标题与投影标题（最早一条非空 `input`），不搜回答正文、工具结果与
  审批理由；正文被清空且没改过名的会话（`title` 为 `null`）也搜不到。搜索作用于首条问题
  的**完整原文**，列表里展示的标题仍截到 60 字符——第 60 字之后的关键词能命中，但标题里
  看不到那段文字。搜索与分页共用 keyset 游标，翻页期间新 run 仍可能让会话重复/跳过
  （ADR-0039 / ADR-0040）
- 翻页期间有新 run 时，会话可能被挤到前面，出现重复或跳过一页；刷新即从第一页重置，
  v1 不保证快照一致性（ADR-0033）
- 库不可用时返回 `503 {"code":"DATABASE_UNAVAILABLE"}`，不会静默返回空列表
  （否则会显示成「你没有历史会话」）
- 取历史：优先用下面的批量接口 `GET /sessions/{session_id}/runs`（一次拿一页正文/引用/
  运行过程）；单条详情路径仍保留。更早的轮次把响应里的 `next_cursor` 带回同一接口。
  继续对话直接用这个 `session_id` 调 `/chat/stream`，服务端按 ADR-0020 续上下文

### 3.4 一页会话详情（ADR-0036）

```http
GET /api/sessions/sess_01H.../runs?limit=20
Authorization: Bearer <token>
```

```json
{
  "session_id": "sess_01H...",
  "items": [
    {
      "run_id": "run_01H...",
      "status": "completed",
      "input": "我电脑连不上打印机了",
      "output": "先重启打印服务……",
      "content_redacted": false,
      "citations": [
        { "chunk_id": 3, "document_id": "doc_print", "ord": 1, "title": "打印机手册", "snippet": "……" }
      ],
      "timeline": [
        { "kind": "tool", "seq": 4, "call_id": "call_1", "tool": "query_cmdb", "args": {}, "write": false, "status": "ok", "duration_ms": 12 }
      ],
      "timeline_available": true,
      "timeline_truncated": false
    }
  ],
  "next_cursor": null
}
```

- 本人：只返回当前用户的会话（没有管理员旁路）；路径里的 `session_id` 属于别人或不存在且没有游标时
  返回 `404 {"detail":"session not found"}`，不区分两种原因（避免泄露存在性）；
  `cursor=` 空串按「没有游标」处理
- `items` 的字段与 `GET /runs/{run_id}` 相同（`input` / `output` / `content_redacted` /
  `citations` / `timeline*`），**但没有 `model_calls`**：历史 transcript 不需要计量明细，
  需要时仍走单条详情
- 分页与 `/runs` 共用 keyset 游标：`limit` 1–50 默认 20，按 `started_at` 倒序，
  取满才给 `next_cursor`；游标翻到空页返回 200 空列表
- 可见性按当前角色**整页一次**判定（ADR-0022）：正文被回收的 run 只影响自己，
  同页其他 run 正常返回；被回收时 `output=null`、`citations=[]`、`timeline=[]`
- `timeline` 只对回答可见且事件未清理的 run 生成（ADR-0035）；`timeline_available=false`
  表示「过程不可用」，不是「没调工具」
- 库不可用时返回 `503 {"code":"DATABASE_UNAVAILABLE"}`

### 3.5 会话重命名（ADR-0040）

```http
PATCH /api/sessions/sess_01H...
Authorization: Bearer <token>
Content-Type: application/json

{"title": "A 楼 3 层打印"}
```

- 只改会话列表里的显示标题，不碰 `runs` 与事件；`run_count`、`updated_at` 与排序都不变
  （排序仍按最近一次 run 活动）
- `title` 裁掉首尾空白后 1–60 字符；空串返回 `422 {"code":"INVALID_TITLE"}`——
  要恢复默认标题请显式传 `null`
- `{"title": null}` 清除自定义标题，显示回退到最早一条非空 `input`
- 成功返回 `204 No Content`（无响应体，不要解析 JSON）
- 标题格式校验先于归属检查：空白或超长标题先返回 422，不因会话是否存在而改变；
  合法标题下，别人的会话与不存在的会话都返回 `404 {"detail":"session not found"}`
  （不泄露存在性）
- 搜索 `q` 同时匹配自定义标题与首条问题（ADR-0039 / ADR-0040）；改名后旧关键词仍可命中
- 库不可用时返回 `503 {"code":"DATABASE_UNAVAILABLE"}`

### 3.6 从列表移除会话（ADR-0041）

```http
DELETE /api/sessions/sess_01H...
Authorization: Bearer <token>
```

- 成功返回 `204 No Content`；重复调用仍 204（幂等）
- 只影响 `GET /sessions` 的列表与 `q` 搜索：该会话不再出现，其他接口不受影响
- **不删数据**：`runs`、事件、审批、引用快照仍按保留期（ADR-0021/0023）保存；
  直接 `GET /runs/{id}`、事件回放、引用预览仍可访问——这是列表级整理，不是权限控制
- 别人的会话与不存在的会话都返回 `404 {"detail":"session not found"}`（不泄露存在性）
- 移除后可以在「已移除的会话」里恢复（§3.7）；成功后前端若移除的是当前会话，会切到一个新会话
- 库不可用时返回 `503 {"code":"DATABASE_UNAVAILABLE"}`

### 3.7 已移除会话的查看与恢复（ADR-0043 / ADR-0047 / ADR-0049）

```http
GET /api/sessions/hidden?limit=20&cursor=eyJ0IjoiMjAyNi0xMS0xMlQwOTozMDowMFoiLCJzIjoic2Vzc18wMUgifQ&q=打印
Authorization: Bearer <token>
```

```json
{
  "items": [
    {
      "session_id": "sess_01H...",
      "title": "打印机离线",
      "run_count": 2,
      "hidden_at": "2026-11-12T09:30:00Z"
    }
  ],
  "next_cursor": "eyJ0IjoiMjAyNi0xMS0xMlQwOTozMDowMFoiLCJzIjoic2Vzc18wMUgifQ"
}
```

```http
DELETE /api/sessions/sess_01H.../hidden
Authorization: Bearer <token>
```

```http
POST /api/sessions/hidden/restore
Authorization: Bearer <token>
Content-Type: application/json

{"session_ids": ["sess_01H...", "sess_02H...", "sess_01H..."]}
```

```json
{
  "restored": 2,
  "requested": 2,
  "items": [
    {"session_id": "sess_01H...", "restored": true},
    {"session_id": "sess_02H...", "restored": true}
  ]
}
```

- `GET /sessions/hidden` 只返回**本人**从列表移除的会话，按 `hidden_at DESC, session_id DESC`；
  `limit` 1–50，默认 50；`cursor` 是 `(hidden_at, session_id)` 的 keyset 游标（base64url JSON），
  当前页取满时返回 `next_cursor`，下一页为空时为 `null`
- 搜索 `q` 与主列表同口径：大小写不敏感，同时匹配显示标题（自定义标题优先）与首条非空
  `input`；**不搜回答正文**。`q` 最长 100 字符，空白按没有搜索处理
- 标题口径与普通会话列表一致：展示截到 60 字符；`run_count` 是该会话仍存在的 run 数
  （移除不删 run）
- 翻页期间恢复/移除会话会让列表变化，可能重复或跳过一页；刷新（重新展开）即重置。
  移除时间本身不会变（重复移除保留第一次时间），所以已加载页的游标仍然稳定
- 非法 `cursor` 返回 `400 {"code":"INVALID_CURSOR"}`；`q` 超过 100 字符返回 422
- 恢复成功返回 `204 No Content`；之后该会话重新出现在 `GET /sessions` 与 `q` 搜索中，
  排序仍按最近一次 run 活动
- 没移除过、或属于别人的会话，都返回 `404 {"detail":"session not found"}`（不泄露存在性）；
  重复恢复同样是 404（已无行可删）
- 恢复只删 `hidden_sessions` 的一行：不重建/不删除 run、事件、审批、引用快照与自定义标题；
  已过保留期的正文不会因此重新出现
- 库不可用时返回 `503 {"code":"DATABASE_UNAVAILABLE"}`；前端折叠区只在首次展开时请求，
  搜索与「加载更多」都带当前关键词/游标，旧响应不会覆盖新结果
- `POST /sessions/hidden/restore` 一次 1–50 个，服务端去重保序；空列表、超过 50 个或空白
  id 返回 422
- 只删**本人**的 `hidden_sessions` 行；不存在、属于别人、或本来就没移除的 id 静默忽略
  （部分成功）。逐条结果的 `restored: false` 刻意合并这三类，不区分「不存在」与「属于
  别人」，避免泄露别人的会话是否存在
- 返回 `{"restored": n, "requested": m, "items": [...]}`；`items` 与去重后的请求顺序一致，
  `requested` 是去重后的数量；未要求逐条结果的旧客户端仍可只读计数；重复调用幂等
  （`restored` 为 0，所有 `items[].restored` 为 false）
- 与单条恢复一样只删行：不重建/不删除 run、事件、审批与引用快照；库故障返回 503

## 4. 审批

```http
GET /api/approvals?status=pending&limit=50
Authorization: Bearer <approver token>
```

```json
{
  "items": [
    {
      "approval_id": "3f1c...",
      "run_id": "9a17...",
      "call_id": "call_1",
      "tool": "create_ticket",
      "args": {"title": "打印机离线", "category": "hardware", "priority": "P2"},
      "risk_level": "medium",
      "status": "pending",
      "requested_by": "u_102",
      "resolved_by": null,
      "reason": null,
      "scope": "once",
      "expires_at": "2026-11-09T04:20:00Z",
      "created_at": "2026-11-09T04:10:00Z",
      "resolved_at": null
    }
  ],
  "next_cursor": "eyJlIjoiMjAyNi0xMS0wOVQwNDoyMDowMCswMDowMCIsImMiOi...",
  "total": 1
}
```

- 审批人角色（`ONCALL_APPROVER_ROLES`，默认 `approver`）看全部待办；普通员工只看自己发起的
- `status` 只接受 `pending|approved|rejected|expired`；打开列表时会把超时待办置 `expired`
- `limit` 默认 50、范围 1–200
- `total` 只在**没有 `cursor` 的第一页**返回，是同一 `status`、同一组已办筛选和同一
  身份范围（审批人看全部，普通员工只看自己发起）下的总数；后续页为 `null`。
  计数与列表分开查询（首屏多一次 `COUNT`），大数据量下可能比列表慢；不返回总数
  时客户端按「未知」处理，不显示「共 N 条」（[ADR-0057](decisions/0057-approval-list-total.md)）
- 排序按 `status` 分流（ADR-0053）：`pending` 按 `(expires_at, created_at,
  approval_id)` 升序，最急的在前；`approved|rejected|expired` 按
  `(resolved_at, approval_id)` 倒序，最近的决议在前（`expired` 的
  `resolved_at` 是过期收敛时刻）
- `cursor` 是 keyset 游标（base64url JSON，最长 512 字符），形状随状态变化：
  待办 `{"e","c","i"}`（ADR-0052），已办 `{"s","r","i"}`（`s` 为
  `approved|rejected|expired`）；已办带筛选时额外有 `"f"`（筛选指纹，ADR-0054）；
  当前页取满才返回 `next_cursor`，下一页为空时
  返回 `items: []` 且游标为 null；非法游标或游标状态不匹配返回
  `400 {"code":"INVALID_CURSOR"}`。游标里的审批 ID 必须是 UUID；Postgres
  存储会在进查询前校验，非 UUID 同样按非法游标返回 400，不会变成 503。
- 已办筛选（ADR-0054，仅 `approved|rejected|expired`）：
  - `tool`：工具名精确匹配，去空白后 1–64 字符（与 `approvals.tool_name` 列宽一致）。
  - `resolved_by`：审批人精确匹配，去空白后 1–64 字符。
  - `resolved_from` / `resolved_to`：`YYYY-MM-DD`，UTC 自然日；开始日含当天
    00:00，结束日不含当天（内部按次日 00:00 处理）。`resolved_from >
    resolved_to` 或 `resolved_to=9999-12-31` 返回
    `422 {"code":"INVALID_RANGE"}`。
  - `status=pending`（或缺省）时带任一筛选参数返回
    `422 {"code":"INVALID_FILTER"}`；待办列表不支持已办筛选。
  - 游标只配合同一 `status` **和同一组筛选条件**：带筛选的已办游标里有 `f`
    指纹，换工具/审批人/日期后复用旧游标返回 `400 INVALID_CURSOR`；不带筛选的
    旧已办游标（`{s,r,i}`）继续可用。
- 示例：`GET /api/approvals?status=approved&tool=create_ticket&resolved_by=u_900&resolved_from=2026-11-01&resolved_to=2026-11-02&limit=50`，
  返回该审批人在 11 月 1 日（UTC；`resolved_to` 不含当天）决议的
  `create_ticket` 审批，按 `resolved_at` 倒序。
- 游标只配合同一个 `status`（及同一组已办筛选条件）使用，待办/已办、
  `approved|rejected|expired` 之间都不能混用；翻页期间审批被决议可能让后续页
  重复/跳过，刷新即回第一页。游标不签名，服务端仍按当前身份过滤
  （ADR-0052 / ADR-0053 / ADR-0054）
- 前端列表在首屏显示「共 N 条」；加载更多后显示「共 N 条，已显示 M 条」，
  切状态/筛选/刷新会重新取第一页总数
- 前端已办列表显示「决议时间」（`resolved_at`），待办仍显示「到期时间」；
  已办还提供工具、审批人、决议日期筛选，筛选条件变化后从第一页重新加载；
  旧已办游标（ADR-0052 的 `{e,c,i}` 或初版 `{r,i}`）失效一次，刷新即回第一页

```http
GET /api/approvals/export?status=approved&tool=create_ticket&resolved_from=2026-11-01
Authorization: Bearer <approver token>
```

```http
HTTP/1.1 200 OK
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="approvals-approved-20261114-050000.csv"
Cache-Control: no-store
X-Export-Count: 2
X-Export-Truncated: false
```

```csv
approval_id,run_id,call_id,tool,risk_level,status,requested_by,resolved_by,scope,created_at,expires_at,resolved_at,reason
3f1c...,9a17...,call_1,create_ticket,medium,approved,u_102,u_900,once,2026-11-01T04:10:00+00:00,2026-11-01T04:20:00+00:00,2026-11-01T04:15:00+00:00,已核对身份
```

- 导出与列表使用同一组参数与身份范围（ADR-0056）：`status`、`tool`、
  `resolved_by`、`resolved_from`、`resolved_to`；不接收 `cursor`/`limit`。
- 排序与列表一致：待办按 `(expires_at, created_at, approval_id)` 升序，已办按
  `(resolved_at, approval_id)` 倒序；筛选只对已办生效，`status=pending` 带任一
  筛选项返回 `422 {"code":"INVALID_FILTER"}`。
- 最多导出 **5000 条**。内部多取一条判断截断；响应头 `X-Export-Count` 是实际
  行数，`X-Export-Truncated` 为 `true` 时表示只导出了当前排序的前 5000 条。
  客户端需要提示用户缩小筛选，不能把截断结果当成全量。
- 列固定为 `approval_id, run_id, call_id, tool, risk_level, status,
  requested_by, resolved_by, scope, created_at, expires_at, resolved_at, reason`；
  **不导出 `args`**（工具参数可能含敏感值，留在审批详情里按权限查看）。
- 时间统一 ISO 8601（UTC）；UTF-8 BOM + CRLF，方便 Excel 打开；以
  `= + - @ \t \r` 开头的单元格前置单引号，防止表格把审批理由当公式执行。
- 审批人可导出全部（仍受筛选约束）；普通员工只能导出自己发起的。响应带
  `Cache-Control: no-store`，不落浏览器缓存。
- 前端按钮使用当前已应用的 `status` + `filters`，通过带 Bearer 的 `fetch`
  下载 Blob；成功后提示行数，截断时提示「已导出前 5000 条」。
- 数据库不可用返回 `503 {"code":"DATABASE_UNAVAILABLE"}`。

```http
GET /api/approvals/stats?days=7&group_by=tool
Authorization: Bearer <approver token>
```

```json
{
  "days": 7,
  "pending_count": 3,
  "oldest_pending_age_s": 5400,
  "decided_count": 12,
  "avg_wait_ms": 1812000,
  "max_wait_ms": 8640000,
  "daily": [
    {"day": "2026-11-09", "decided_count": 5, "avg_wait_ms": 1200000},
    {"day": "2026-11-10", "decided_count": 7, "avg_wait_ms": 2346000}
  ],
  "groups": [
    {"key": "create_ticket", "decided_count": 7, "avg_wait_ms": 1600000, "max_wait_ms": 3600000},
    {"key": "query_cmdb", "decided_count": 5, "avg_wait_ms": 2100000, "max_wait_ms": 8640000}
  ],
  "groups_truncated": false
}
```

- 仅审批人角色可读，普通员工 `403 {"code":"FORBIDDEN"}`；`days` 范围 1–90，默认 7
- `pending_count` 是当前**未过期**待办的数量（`status=pending` 且 `expires_at > now`）；
  `oldest_pending_age_s` 是最老未过期待办的已等秒数（无待办为 `null`）
- `decided_count` 只统计窗口内 `approved` + `rejected`；等待 = `resolved_at - created_at`，
  过期（`expired`）不计入人工等待，负数按 0 处理
- 统计前会先收敛超时待办；聚合时还会排除已过期的 `pending`（即使单轮收敛上限没扫到），
  所以刚过 TTL 的单不会继续算作积压
- `daily` 按 **UTC 日期**分桶，只列窗口内真正有决议的日期（稀疏不补零）；每项
  `decided_count` / `avg_wait_ms` 与上面的已决议口径一致；前端提供 7/30/90 天切换，
  `days` 与 `daily` 使用同一个窗口（[ADR-0050](decisions/0050-approval-trend.md)）
- `group_by` 可选 `tool` / `approver`，默认不分组；只聚合窗口内 `approved` + `rejected`，
  `pending` 没有审批人归属、`expired` 不算人工决议，均不进入分组；各分组之和等于
  `decided_count`（`groups_truncated=false` 时）
- 分组键：`tool` 用 `tool_name`；`approver` 用 `resolved_by`，缺失归入 `unknown`；
  按单数降序、键升序取前 20 组，超过时 `groups_truncated=true`
- 不返回逐条 `resolved_by`；`approver` 分组的 key 是审批人 `user_id`，只给审批人看聚合数字
  （[ADR-0051](decisions/0051-approval-stats-groups.md)）
- 库不可用返回 503，不返回 0 冒充「没有积压」

```http
POST /api/approvals/{approval_id}/resolve
{ "decision": "approved", "reason": "已确认用户身份", "scope": "once" }
```

```json
{
  "approval": { "...": "同列表项，status=approved" },
  "run_id": "9a17...",
  "run_status": "completed"
}
```

- `scope`: `once` | `session`（本会话内同类工具不再询问；授权有效期 `ONCALL_APPROVAL_GRANT_HOURS`）
- 校验：审批人必须属于 `ONCALL_APPROVER_ROLES`，且 **`resolved_by != requested_by`**（不能自己批自己）；否则 `403 {"code":"FORBIDDEN"}`
- 幂等：重复 resolve 返回首次结果，不重复执行工具
- 通过：追加 `approval.resolved`，从挂起快照恢复执行，再追加 `tool.result` / `message.*` / `run.completed`
- 拒绝/过期：追加 `approval.resolved` + `run.failed`，run 转 `failed(error_code=APPROVAL_REJECTED|APPROVAL_TIMEOUT)`
- 认证失败 `401`，审批不存在 `404 {"code":"APPROVAL_NOT_FOUND"}`
- 数据库不可用：`503 {"code":"DATABASE_UNAVAILABLE","message":"database unavailable"}`
- 竞态保护：`approval.required` 尚未落库时 run 仍是 `running`，此时 resolve 返回
  `409 {"code":"APPROVAL_NOT_READY"}`，避免 `resolved` 排在 `required` 前面导致 run 卡住

## 5. 管理接口与知识库读取示例

> 本节除「引用跳全文」外都是管理接口（要求 `ONCALL_ADMIN_ROLES`）；
> 引用全文只要求登录，且受文档级可见性约束（[ADR-0018](decisions/0018-citation-fulltext-preview.md)、
> [ADR-0019](decisions/0019-document-level-access.md)）。

### 成本汇总

```http
GET /api/admin/cost/summary?from=2026-11-01&to=2026-11-30&group_by=model
```

```json
{
  "total_cents": 4820,
  "calls": 317,
  "items": [
    { "key": "qwen2.5:7b", "calls": 240, "token_in": 182000, "token_out": 41000, "cost_cents": 980 },
    { "key": "gpt-4o-mini", "calls": 77, "token_in": 61000, "token_out": 12000, "cost_cents": 3840 }
  ]
}
```

- 管理接口，要求 `ONCALL_ADMIN_ROLES`；`from`/`to` 是 UTC 自然日，`to` 闭区间；
  默认最近 7 天，最长 366 天；`from > to` 返回 `422 INVALID_RANGE`
- `group_by=day` 按时间正序返回趋势；`model` / `user` 按花费倒序
- 聚合源是 `model_calls`，不是缓存的汇总表；与 `/runs/{id}` 的 token/cost 同源

### 按用户日预算（ADR-0026）

```http
GET /api/admin/budgets
```

```json
{
  "default_cents": 0,
  "overrides": [
    { "user_id": "u_205", "daily_cents": 120, "updated_by": "admin_1", "updated_at": "2026-11-11T02:10:00Z" }
  ]
}
```

- `default_cents` 来自 `ONCALL_USER_DAILY_BUDGET_CNY`（0 = 不限）；`overrides` 按 `user_id` 排序
- 写入：`PUT /api/admin/budgets/u_205`，body `{"daily_cents": 120}`；返回库里的行（含
  `updated_at`）。`daily_cents` 取值 0–1,000,000（0 = 该用户不限），越界 422；
  `user_id` 不允许空白
- 删除：`DELETE /api/admin/budgets/u_205` → 204；删除不存在的覆盖也是 204（幂等）。
  删除才回到默认值，写 0 是"显式不限"
- 优先级：网关**先扣全局、再扣个人**。个人额度大于全局日预算时个人额度永远不会先触发
  （全局先拦），管理页不阻止这种配置，但要知道它等于没设
- 生效方式：网关在**每次模型调用前**读一次上限（2s 缓存）；额度不足时在调用前拒绝，
  run 收敛到 `run.failed(BUDGET_EXCEEDED)`（`payload.category=model`），被拒的这次调用
  不产生费用，也不占当天的全局额度。被拦下不是 429——429 只用于请求限流
- 只在真实模型路径生效：mock 模式不经过网关、成本恒为 0，个人额度不会触发
- 账本从配置生效后的第一次调用开始累计：当天此前已花的钱不计入个人额度（花费真相源
  仍是 `/admin/cost/summary`；账本侧的今日已用见下面的 `/admin/budgets/usage`，
  两个口径不同，见 ADR-0026 / ADR-0028 的「待定」）

### 预算今日用量（ADR-0028）

```http
GET /api/admin/budgets/usage
```

```json
{
  "day": "2026-11-11",
  "stale_after_s": 300.0,
  "global_usage": {
    "limit_cents": 500,
    "spent_cents": 120,
    "reserved_cents": 20,
    "reservation_count": 1,
    "stale_count": 0,
    "stale_cents": 0,
    "oldest_age_s": 2.1
  },
  "users": [
    {
      "user_id": "u_205",
      "spent_cents": 40,
      "reserved_cents": 10,
      "reservation_count": 1,
      "stale_count": 0,
      "stale_cents": 0,
      "oldest_age_s": 2.1
    }
  ]
}
```

- **账本口径**：`spent_cents` 含未结算预扣，是网关判断额度时看到的数字；不是
  `model_calls` 的实际成本。三个口径互不替代：配置看 `/admin/budgets`、账本看本接口、
  实际成本看 `/admin/cost/summary`
- `stale_after_s` 目前固定 300 秒；预扣年龄超过它的计入 `stale_count` / `stale_cents`，
  说明进程可能崩在 reserve 与 settle 之间（UTC 日切后账本 TTL 自愈）。报表只提示，
  不自动回冲
- 只读账本：不读覆盖表；个人上限请与 `GET /admin/budgets` 合并。账本不可用返回
  503 `LEDGER_UNAVAILABLE`，**不**降级为内存账本（否则 Redis 故障会显示成没花钱）
- `users` 只含当天有过预扣或花费的用户，按 `user_id` 排序；没有个人账本消费的人不出现
- 旧格式预扣（滚动升级前写入、没有时间戳）：不计入 `stale_count`，也不参与
  `oldest_age_s`；当天所有预扣都是旧格式时 `oldest_age_s` 为 null
- admin only

### 知识库上传与重建索引（W2 D7/D8）

```http
POST /api/admin/kb/documents
Authorization: Bearer <admin token>
Content-Type: multipart/form-data

file=@vpn-guide.pdf
visibility=public          # 可选，public（默认）| roles
allowed_roles=            # 可选，visibility=roles 时逗号分隔，如 hr,finance
```

```json
{
  "document": {
    "id": "9d0f...",
    "title": "VPN 连接失败排查指南",
    "source": "vpn-guide.pdf",
    "version": null,
    "checksum": "6f1c...",
    "chunk_count": 5,
    "status": "indexed",
    "visibility": "public",
    "allowed_roles": [],
    "created_at": "2026-11-09T01:00:00Z"
  },
  "chunks": [
    {
      "ord": 1,
      "heading": "VPN 连接失败排查指南 > 快速判断",
      "content": "VPN 连不上时先确认三件事……",
      "page": null,
      "is_table": false
    }
  ]
}
```

- 支持 PDF / DOCX / MD / TXT；PDF 只取文本层（扫描件返回 `422 PARSE_FAILED`，v1 不做 OCR）
- 同一 `source` 再次上传会覆盖旧文档（先删后插，`document_id` 会变化）
- `413 FILE_TOO_LARGE`：超过 `ONCALL_KB_MAX_UPLOAD_MB`（默认 10MB）
- `503 EMBEDDING_FAILED` / `DATABASE_UNAVAILABLE`：向量化或写库失败，可重试
- 上传响应里的 `chunks` 最多返回前 50 条（看全量用 `document.chunk_count` 判断）
- 可见性（ADR-0019）：`visibility=public` 时不允许带 `allowed_roles`；`visibility=roles`
  至少要一个角色；角色名只允许字母、数字、`_ . -`，最长 32。违反返回 `422 INVALID_ARGS`
- `POST /api/admin/kb/reindex` 返回 `{"chunks": 156}`：用当前 embedder 重算所有切片的向量与分词，**不重新切分源文件**

`GET /api/admin/kb/documents/{id}?preview=20` 返回文档字段（与上传响应一致）+ 切片预览：

```json
{
  "document": { "id": "9d0f...", "title": "VPN 连接失败排查指南", "chunk_count": 5 },
  "chunks": [{ "ord": 1, "heading": "VPN 连接失败排查指南 > 快速判断", "content": "VPN 连不上时……", "page": null }]
}
```

> 预览不返回 `is_table`：该标记只来自本次上传的切分结果，没有落库（docs/02 §2.6），
> 返回恒为 `false` 会误导调用方。

### 改可见范围（W6 后补，ADR-0019）

```http
PATCH /api/admin/kb/documents/9d0f.../access
Authorization: Bearer <admin token>
Content-Type: application/json

{ "visibility": "roles", "allowed_roles": ["hr"] }
```

返回与列表项相同的文档对象（含 `visibility` / `allowed_roles`）。

- **整体替换**：`visibility` 与 `allowed_roles` 两项都要给出（缺字段是 FastAPI 的标准
  422 校验错误），空 body 不会被解释成「改成公开」
- **不重新切分**：`chunk_id` 保持不变，已有引用继续可点。为了改权限而重传文件会让
  `document_id` 变化，历史引用全部失效，所以单给一个只改权限的入口
- `422 INVALID_ARGS`：可见性取值非法或角色清单与可见性矛盾；`404 NOT_FOUND`：文档不存在
- 保存后立即生效：下一次检索就按新范围过滤，不需要重建索引

### 引用跳全文（W5 D24）

```http
GET /api/kb/documents/9d0f.../preview?chunk_id=10231&ord=4
Authorization: Bearer <任意登录用户>
```

```json
{
  "document": {
    "id": "9d0f...",
    "title": "VPN 连接失败排查指南",
    "source": "vpn-guide.pdf",
    "version": null,
    "checksum": "6f1c...",
    "chunk_count": 5,
    "status": "indexed",
    "visibility": "public",
    "allowed_roles": [],
    "created_at": "2026-11-09T01:00:00Z"
  },
  "chunks": [
    {
      "chunk_id": 10231,
      "ord": 1,
      "heading": "VPN 连接失败排查指南 > 快速判断",
      "content": "VPN 连不上时先确认三件事……",
      "page": null
    }
  ],
  "focused_chunk_id": 10231,
  "total_chunks": 5,
  "truncated": false
}
```

- **只要求登录，不要求管理员**，但受文档级可见性约束（[ADR-0018](decisions/0018-citation-fulltext-preview.md)、
  [ADR-0019](decisions/0019-document-level-access.md)）：`public` 文档都能读，`roles` 文档要求
  角色交集，`admin` 作为知识库所有者不受限。**不可见与不存在都返回 `404 NOT_FOUND`** ——
  403 会泄露「这篇文档存在」
- 刻意没有列表/浏览接口，员工只能凭已知的 `document_id` 打开；接口**不校验**该 id
  是否真的出现在调用方的引用里（那要绑定 run 归属），靠「无列表 + UUID 不可猜」收敛；
  管理操作仍走 `/admin/kb/*`
- `chunk_id` 优先（引用自带）、`ord` 兜底（重切后 chunk_id 会变）；都对不上时
  `focused_chunk_id: null`，前端只展示全文并提示「引用位置未找到」，**不猜段落**
- 单次上限 200 个切片 / 20 万字符；切片数或字符预算在引用段前用尽时，
  窗口会前移或从引用段重新开窗，保证焦点在返回结果里；超出返回 `truncated: true`
- `404 NOT_FOUND`：文档不存在、已重新上传（`document_id` 变化）或 id 不是 UUID
- `503 DATABASE_UNAVAILABLE`：知识库暂不可用
- 响应是**按切片重组**的正文，不是原始文件渲染：PDF 排版与表格样式会丢，前端需写明

W5 D21 再做知识库管理页；当前接口返回的 `chunks` 已经能直接看到 `heading_path` 与切片内容。

### 工具注册与试调用（W5 D22）

```http
GET /api/admin/tools
Authorization: Bearer <admin token>
```

```json
{
  "items": [
    {
      "name": "query_cmdb",
      "description": "查当前用户名下资产",
      "input_schema": { "type": "object", "properties": { "asset_id": { "type": "string" } } },
      "is_write": false,
      "timeout_ms": 2000,
      "roles": [],
      "enabled": true,
      "code_enabled": true,
      "overridden": false,
      "source": "builtin"
    }
  ]
}
```

- `roles=[]` 表示所有登录用户；`overridden=true` 表示本环境存了启用/角色覆盖
- `code_enabled=false` 是代码里的硬边界，管理页不能把它打开

```http
PATCH /api/admin/tools/query_cmdb
{ "enabled": false }
```

- `enabled: false` 禁用；`enabled: null` 删除启用覆盖、回到代码默认值（**保留**角色覆盖）
- 尝试把代码 `enabled=false` 的工具打开 → `422 TOOL_LOCKED`；未知工具 `404 TOOL_NOT_FOUND`
- 只需要改启用开关时用 PATCH；角色矩阵走 `PUT /admin/perm-matrix`

```http
POST /api/admin/tools/query_cmdb/test
{ "args": {} }
```

返回 `{ tool, decision, status, result, error, error_kind, duration_ms, attempts }`，
**强制走治理链路**（权限用当前管理员身份），不绕过 guard：

- 只读工具真实执行；参数里的身份字段（`user_id` / `role` …）仍按 `RESERVED_ARGS` 拒绝
- `owner_id` 已从 `query_cmdb` 的 schema 删除，由当前管理员身份注入：传 `owner_id` 会触发
  参数校验失败，传 `requester` 会命中 `RESERVED_ARGS`，两者都不会执行 handler
- 写工具只返回 `decision=requires_approval`，**不会真的执行 handler**
- 被禁用或角色不匹配时返回 `decision=denied`

### 权限矩阵（W5 D23）

```http
GET /api/admin/perm-matrix
```

```json
{
  "roles": ["employee", "approver", "admin"],
  "tools": [
    {
      "name": "query_cmdb",
      "description": "查当前用户名下资产",
      "is_write": false,
      "enabled": true,
      "code_enabled": true,
      "default_roles": [],
      "default_enabled": true,
      "roles": [],
      "overridden": false
    }
  ]
}
```

`PUT /api/admin/perm-matrix` 按工具部分更新（未列出的工具保持原样）：

```json
{
  "tools": [
    { "name": "query_cmdb", "enabled": true, "roles": ["admin"] },
    { "name": "create_ticket", "enabled": true, "roles": [] }
  ]
}
```

- `roles: []` = 所有登录用户；角色必须来自响应里的 `roles` 目录（v1 内置
  `employee/approver/admin`，并合并 `ONCALL_ADMIN_ROLES` / `ONCALL_APPROVER_ROLES`）
- 与代码默认值相同的工具不写覆盖表；提交默认值即可删除该工具的覆盖
- 未知角色/工具、重复工具 → `422 INVALID_ARGS`；代码禁用工具被打开 → `422 TOOL_LOCKED`
- 保存后本进程立即生效；多副本部署最长 `2s` 生效（短 TTL 缓存，见 ADR-0014）
- 管理页读配置失败返回 `503 DATABASE_UNAVAILABLE`，**不用旧快照冒充现状**；
  只有工具执行路径允许退回上一份快照（否则库抖动会让所有工具调用一起失败）

### 工具配置变更历史（ADR-0037）

```http
GET /api/admin/tools/create_ticket/history?limit=20
Authorization: Bearer <admin token>
```

```json
{
  "items": [
    {
      "id": 12,
      "tool_name": "create_ticket",
      "changed_by": "admin_1",
      "changed_at": "2026-11-12T10:00:00Z",
      "source": "matrix",
      "before": { "enabled": null, "roles": [] },
      "after": { "enabled": false, "roles": null }
    }
  ]
}
```

- 只有真正发生变化的工具才落行；无变化的 PATCH / 矩阵保存不产生记录
- `before` / `after` 是完整覆盖快照：`null` 表示没有覆盖（继承代码默认），
  `enabled: null` 表示启用继承，`roles: []` 表示所有登录用户；删除覆盖也会留下
  「恢复默认」的记录
- `source`：`tool` = PATCH 启用开关，`matrix` = 权限矩阵整表保存；同一次矩阵保存
  按工具各一行
- 默认返回最近 20 条，最多 100；记录按 `changed_at DESC, id DESC` 排序
- 不要求工具仍在注册表：按名字查历史，工具下线/改名后仍可查；从未注册过的名字返回空
  列表（`items: []`），不返回 404
- 库不可用 `503 DATABASE_UNAVAILABLE`，不把故障显示成「没有历史」
- 历史长期保留，不随 run 事件或审批快照清理；只读，不提供回滚按钮（回滚应是一次
  新的显式保存）

## 6. 版本与兼容

- 路径带 `/api`，不做版本号（v1 单客户端，避免过度设计）
- 事件 `type` 只增不改；新增字段必须可选
- 前端遇到未知 `type` 必须**忽略而不是崩溃**（用 `switch` 的 default 分支）
