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
- 管理接口（`/api/admin/kb/*` 与 `/api/admin/tools/*`、`/api/admin/perm-matrix`、`/api/admin/cost/*`）额外要求 `ONCALL_ADMIN_ROLES` 中的任一角色（默认 `admin`）；不满足返回 `403 {"code":"FORBIDDEN","message":"需要管理员角色"}`。工具/角色矩阵的覆盖存 `tool_settings`（ADR-0014）。
- 例外是引用跳全文 `GET /api/kb/documents/{id}/preview`：它属于对话链路而不是管理面，只要求登录（与检索同一可见性，ADR-0018）。

## 1. 接口清单

| 方法 | 路径 | 说明 | 阶段 |
|---|---|---|---|
| GET | `/health` | 健康检查（含 db/redis 探活） | W1 D1 |
| POST | `/chat/stream` | 发起一次对话，返回 SSE 流 | W1 D3 |
| GET | `/runs` | 运行列表（分页、按状态筛选） | W4 D19 |
| GET | `/runs/{run_id}` | 单次运行详情（含指标与模型调用明细） | W1 D4 / W4 D19 |
| GET | `/runs/{run_id}/events?after_seq=` | 补拉事件（断线续传，兼容 `Last-Event-ID`） | W1 D4 |
| GET | `/runs/{run_id}/stream` | 重连增量流（可选，v1 用轮询替代） | — |
| POST | `/approvals/{id}/resolve` | 审批通过/拒绝 | W3 D14 |
| GET | `/approvals?status=pending&limit=50` | 待办审批列表（含已办筛选） | W3 D14 / W5 D23 |
| POST | `/admin/kb/documents` | 上传知识文档（multipart，≤10MB） | W2 D7 |
| GET | `/admin/kb/documents` | 知识库文档列表 + chunk 总数 | W2 D7 |
| GET | `/admin/kb/documents/{id}?preview=20` | 文档详情与切片预览（含 heading_path） | W2 D7 |
| PATCH | `/admin/kb/documents/{id}/access` | 改文档可见范围（不重切，`chunk_id` 不变） | W6 后补 |
| GET | `/kb/documents/{id}/preview?chunk_id=&ord=` | 引用跳全文（登录即可；受文档可见性约束，不可见 404） | W5 D24 |
| POST | `/admin/kb/reindex` | 重建索引（用当前 embedder 重算向量） | W2 D8 |
| GET | `/admin/tools` | 工具注册表（含生效角色/启用状态） | W3 D12 / W5 D22 |
| PATCH | `/admin/tools/{name}` | 启用/禁用工具（`enabled: null` 恢复默认） | W5 D22 |
| POST | `/admin/tools/{name}/test` | 工具试调用（强制走治理链路） | W5 D22 |
| GET | `/admin/perm-matrix` | 角色 × 工具矩阵 | W3 D12 / W5 D23 |
| PUT | `/admin/perm-matrix` | 更新矩阵（按工具部分更新） | W5 D23 |
| GET | `/admin/cost/summary?from=&to=&group_by=day\|model\|user` | 成本聚合 | W4 D19 |
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
{ "events": [ ... ], "next_seq": 42, "run_status": "running" }
```

- `after_seq` 与 `Last-Event-ID` 都支持：**查询参数优先**；两者都没传按 0 处理；非法 header 也按 0（不因续传参数把主流程打成 422）
- `limit` 默认 200、上限 500；`next_seq` 是本次返回的最后一个 `seq`（没有新事件时等于请求的起点）
- run 不存在返回 `404`，不要用空数组掩盖

### 3.1 运行列表

```http
GET /api/runs?limit=20&status=failed&cursor=<opaque>
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
      "started_at": "2026-11-09T02:11:03.120Z",
      "finished_at": "2026-11-09T02:11:04.400Z"
    }
  ],
  "next_cursor": "MjAyNi0xMS0wOVQwMjoxMTowMy4xMjArMDB8OWExNw=="
}
```

- 只返回当前用户的 run；`status` 可选，值同事件流状态
- `limit` 默认 20、上限 100；`next_cursor` 为 `null` 表示没有下一页
- `cursor` 是不透明字符串（base64 的 `started_at|run_id`）；非法 cursor 返回
  `400 {"code":"INVALID_CURSOR"}`，不要静默从头开始
- `failure_category` 只对失败 run 有值，用来回答「失败在模型、工具、审批还是护栏」

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
  "started_at": "2026-11-09T02:11:03.120Z",
  "finished_at": "2026-11-09T02:11:04.400Z",
  "input": "我电脑连不上打印机了",
  "output": "你名下的笔记本…",
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

## 4. 审批

```http
GET /api/approvals?status=pending
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
  ]
}
```

- 审批人角色（`ONCALL_APPROVER_ROLES`，默认 `approver`）看全部待办；普通员工只看自己发起的
- `status` 只接受 `pending|approved|rejected|expired`；打开列表时会把超时待办置 `expired`
- `limit` 默认 50、范围 1–200；`expires_at` 升序，同时间按 `created_at` 升序

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
      "description": "按 owner 查设备信息",
      "input_schema": { "type": "object", "properties": { "owner_id": { "type": "string" } } },
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
{ "args": { "owner_id": "u_102" } }
```

返回 `{ tool, decision, status, result, error, error_kind, duration_ms, attempts }`，
**强制走治理链路**（权限用当前管理员身份），不绕过 guard：

- 只读工具真实执行；参数里的身份字段（`user_id` / `role` …）仍按 `RESERVED_ARGS` 拒绝
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
      "description": "按 owner 查设备信息",
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

## 6. 版本与兼容

- 路径带 `/api`，不做版本号（v1 单客户端，避免过度设计）
- 事件 `type` 只增不改；新增字段必须可选
- 前端遇到未知 `type` 必须**忽略而不是崩溃**（用 `switch` 的 default 分支）
