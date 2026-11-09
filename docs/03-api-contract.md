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
- 管理接口（`/api/admin/kb/*`）额外要求 `ONCALL_ADMIN_ROLES` 中的任一角色（默认 `admin`）；不满足返回 `403 {"code":"FORBIDDEN","message":"需要管理员角色"}`。权限矩阵 W3 D12 再落库。

## 1. 接口清单

| 方法 | 路径 | 说明 | 阶段 |
|---|---|---|---|
| GET | `/health` | 健康检查（含 db/redis 探活） | W1 D1 |
| POST | `/chat/stream` | 发起一次对话，返回 SSE 流 | W1 D3 |
| GET | `/runs` | 运行列表（分页） | W4 D19 |
| GET | `/runs/{run_id}` | 单次运行详情（含指标） | W1 D4 |
| GET | `/runs/{run_id}/events?after_seq=` | 补拉事件（断线续传，兼容 `Last-Event-ID`） | W1 D4 |
| GET | `/runs/{run_id}/stream` | 重连增量流（可选，v1 用轮询替代） | — |
| POST | `/approvals/{id}/resolve` | 审批通过/拒绝 | W3 D14 |
| GET | `/approvals?status=pending` | 待办审批列表 | W3 D14 |
| POST | `/admin/kb/documents` | 上传知识文档（multipart，≤10MB） | W2 D7 |
| GET | `/admin/kb/documents` | 知识库文档列表 + chunk 总数 | W2 D7 |
| GET | `/admin/kb/documents/{id}?preview=20` | 文档详情与切片预览（含 heading_path） | W2 D7 |
| POST | `/admin/kb/reindex` | 重建索引（用当前 embedder 重算向量） | W2 D8 |
| GET | `/admin/tools` | 工具注册表 | W3 D12 |
| POST | `/admin/tools/{name}/test` | 工具试调用 | W5 D22 |
| GET | `/admin/perm-matrix` | 角色 × 工具矩阵 | W3 D12 |
| PUT | `/admin/perm-matrix` | 更新矩阵 | W5 D23 |
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
| `run.completed` | `{status, steps, token_in, token_out, cost_cents, duration_ms}` | 置 completed，显示成本 |
| `run.failed` | `{error_code, message, at_step}` | 置 failed，显示重试 |
| `heartbeat` | — | 忽略（或用于探测超时） |

> W1 没有 LLM 调用：`run.started.model` 默认是 `rule-engine`，W4 网关接入后才是真实模型名。
> W2 的 `retrieve` 是**节点**而不是工具，所以只发 `step.*`，不发 `tool.call`；
> `message.completed.citations` 为本次实际用到的 1-3 条（无命中时为空数组）。
> W3 的节点顺序固定为 `intake → classify → retrieve → plan → act → verify → finalize`；
> 写操作在 `act` 挂起，run 停在 `awaiting_approval`，审批通过后从 `approve → act → verify → finalize` 继续。
> OpenAPI 已声明 `BearerAuth` 安全方案（`fastapi.security.HTTPBearer`），Swagger 可直接 Authorize。

### 2.4 错误语义（三种，不要混）

| 情况 | HTTP/事件 | 前端表现 |
|---|---|---|
| 请求本身不合法（未鉴权、字段缺失） | `4xx` JSON `{code,message}`（401 见 §0；422 是 FastAPI 校验格式），**不建 SSE** | 表单报错 / 提示设置 Token |
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

### 3.1 单次运行详情

```http
GET /api/runs/{run_id}
```

```json
{
  "run_id": "9a17959c-6ee7-4015-bf2d-addc2c79f168",
  "status": "completed",
  "user_id": "u_102",
  "session_id": "sess_01H...",
  "intent": "hardware",
  "model": "qwen2.5:7b",
  "step_count": 6,
  "max_steps": 12,
  "token_in": 1820,
  "token_out": 310,
  "cost_cents": 3,
  "error_code": null,
  "event_count": 23,
  "started_at": "2026-11-09T02:11:03.120Z",
  "finished_at": "2026-11-09T02:11:04.400Z",
  "input": "我电脑连不上打印机了",
  "output": "你名下的笔记本…"
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
- 竞态保护：`approval.required` 尚未落库时 run 仍是 `running`，此时 resolve 返回
  `409 {"code":"APPROVAL_NOT_READY"}`，避免 `resolved` 排在 `required` 前面导致 run 卡住

## 5. 管理接口示例

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

### 知识库上传与重建索引（W2 D7/D8）

```http
POST /api/admin/kb/documents
Authorization: Bearer <admin token>
Content-Type: multipart/form-data

file=@vpn-guide.pdf
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

W5 D21 再做知识库管理页；当前接口返回的 `chunks` 已经能直接看到 `heading_path` 与切片内容。

### 工具试调用

```http
POST /api/admin/tools/search_kb/test
{ "args": { "query": "VPN 连接失败" } }
```

返回 `{ status, result, duration_ms }`，**强制走治理链路**（权限用当前管理员身份），不绕过 guard。

## 6. 版本与兼容

- 路径带 `/api`，不做版本号（v1 单客户端，避免过度设计）
- 事件 `type` 只增不改；新增字段必须可选
- 前端遇到未知 `type` 必须**忽略而不是崩溃**（用 `switch` 的 default 分支）
