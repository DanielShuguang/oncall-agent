# 06 · 工具治理

> 这是整个项目最值钱的一章。面试官问"工具调用超时怎么办""谁来判断能不能写库"，答案全在这里。

## 1. 先立规矩

> **模型负责产出意图和参数，判断和执行必须在业务代码里。**
> 四类操作永远不由模型决定：权限、写库、金额、审批。

## 2. 工具定义

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                  # 唯一名，模型只能填这个
    description: str           # 给模型看的能力说明
    input_schema: dict         # JSON Schema，同时用于模型约束与入参校验
    handler: Callable          # 实际执行
    is_write: bool = False     # 写操作 → 必须审批
    timeout_ms: int = 3000     # 每个工具单独配，不共用全局
    roles: tuple[str, ...] = ()# 允许调用的角色（空 = 所有登录用户）
    retryable: tuple[str, ...] = ("timeout", "network")  # 哪些错误可重试
    inject_identity: bool = False  # handler 需要服务端身份时由治理层注入
```

**身份注入**：`create_ticket` 的 `requester` 不能来自模型参数（`user_id`/`identity`/
`requester`/`requested_by`/`resolved_by` 都在保留字段黑名单里）。`ToolGuard` 在调用
handler 时用 `spec.handler(**args, identity=identity)` 注入会话身份 —— 模型只能决定
"开什么单"，决定不了"以谁的名义开"。

**入参白名单**：`validate_args` 会拒绝 `input_schema.properties` 之外的字段，并校验
`enum`。模型多塞一个 `foo` 不会被静默忽略，也不会带进 handler —— 记 `invalid_args`
让模型改参数，而不是让它绕过 schema。

**为什么超时按工具配**：查 CMDB 是 200ms 的内网调用，检索是 800ms，远程诊断可能 10s。用一个全局 5s 会让慢工具被误杀、快工具的故障被掩盖。

## 3. 五道闸门（执行顺序不可换）

```
模型产出 {tool, args}
   │
 ① 存在性：工具是否已注册？
   │        否 → DENIED(TOOL_NOT_REGISTERED)，不暴露"有哪些工具"
 ② 保留字段：args 里是否含 user_id / role / permission / tenant？
   │        是 → DENIED(RESERVED_ARG)，身份只能由服务端会话注入
 ③ 权限：当前用户角色 ∈ spec.roles？
   │        否 → DENIED(PERMISSION)，记审计日志
 ④ 白名单：该角色在本环境是否被允许启用此工具？（配置开关）
   │        否 → DENIED(DISABLED)
 ⑤ 写操作：is_write == true？
   │        是 → 挂起，发 approval.required，不执行
   └────────→ 否 → 执行
```

实现见 `server/app/tools/registry.py` 的 `ToolGuard.execute()`。W5 起，在存在性检查之后、
③/④ 之前会先应用 `tool_settings` 的环境覆盖（禁用/角色），生效规则与边界见 docs/02 §2.5；
代码里的 `enabled=False` 不能被管理页打开。

管理面试调用（`POST /admin/tools/{name}/test`）走同一个 `ToolGuard`：只读工具真实执行，
写工具只返回 `requires_approval`，参数里的身份字段仍按保留字段拒绝。禁止在管理接口里
直接调 handler，否则试调用会成为绕过治理的后门。

W4 的 plan 是模型产出的，节点内会先用同一个 `validate_args` 过滤明显非法的调用
（未知工具 / 未知参数 / enum 错 / 模糊输入计划写操作），全部非法时退回规则计划；
`act` 执行前仍会再走一遍五道闸门。**这不是重复校验**：plan 的校验是降级策略，
act 的校验才是强制边界，模型不能靠"计划阶段漏网"绕过治理。

## 4. 超时与取消

```python
async with asyncio.timeout(spec.timeout_ms / 1000):
    result = await spec.handler(**args)
```

坑：**`asyncio.timeout` 只是"上层不再等"，协程内部的阻塞调用不会自动停**。所以：

- `handler` 内部必须支持 `CancelledError`（HTTP 客户端用 `httpx.AsyncClient(timeout=...)`，DB 查询带 `statement_timeout`）
- 超时后要把这个工具标记为"结果未知"，**不能直接重试写操作**（可能已生效）

> 写操作的超时重试必须配合幂等键（`idempotency_key = run_id + call_id`），否则会重复开单。

## 5. 重试策略：按错误类型分

| 错误类型 | 可重试 | 策略 |
|---|---|---|
| `timeout` | ✅ | 最多 2 次，指数退避 200ms → 400ms + 抖动 |
| `network`（连接失败/5xx） | ✅ | 同上 |
| `rate_limited`（429） | ✅ | 退避更长，尊重 `Retry-After` |
| `invalid_args`（400/校验失败） | ❌ | 重试一百次也没用，直接把错误回给模型让它改参数 |
| `permission` | ❌ | 转人工，不重试 |
| `not_found` | ❌ | 返回空结果，让模型换策略 |

```python
def should_retry(err: ToolError, attempt: int, spec: ToolSpec) -> bool:
    if attempt >= 3 or err.kind not in spec.retryable:
        return False
    if spec.is_write and not err.idempotent_safe:
        return False
    return True
```

抖动是必须的：固定间隔会让所有重试在同一毫秒打爆下游。`sleep = base * 2**attempt * (0.5 + random())`。

## 6. 降级

每个工具必须声明降级行为，不然就是"一个工具挂了，整个 Agent 哑了"。

| 工具 | 失败降级 |
|---|---|
| `query_cmdb` | 提示"数据可能过期"并按通用步骤继续；W3 接入会话资产缓存后改用缓存值 |
| `search_kb` | 降级为只走 BM25（跳过向量），或直接兜底话术 + 转人工 |
| `query_tickets` | 返回空，继续流程，提示"未查到历史工单" |
| `run_diagnostic` | 跳过诊断，直接建议开单（人工排查） |
| `create_ticket` | **不降级**，明确报错让用户手动开单（写操作不能猜） |

Agent 层面：单个工具失败不中断整个 run，`tool.result` 记 `status=error`，`verify` 节点决定是否继续。

## 7. 审批（Human-in-the-loop）

| 项 | 规则 |
|---|---|
| 触发 | `is_write == true`，或风险等级 ≥ medium |
| 展示 | 工具名 + 参数预览（人类可读）+ 风险说明 + 影响范围 |
| 审批人 | 角色 ∈ `ONCALL_APPROVER_ROLES`（默认 `approver`），且 **≠ 发起人** |
| 范围 | `once` / `session`（本会话同类不再问，落 `approval_grants`，按 `user_id + session_id + tool` 隔离，默认 8 小时过期） |
| 过期 | 默认 10 分钟（`ONCALL_APPROVAL_TTL_MIN`），超时 → `expired` → run 失败并转人工 |
| 幂等 | 重复 resolve 返回首次结果，不重复执行工具（存储层 `WHERE status='pending'` 原子迁移） |
| 恢复 | 通过后从 `approvals.state` 快照恢复 `act`，只执行挂起的那一次调用 |
| 审计 | 谁、何时、批了什么、理由、参数快照与上下文，全部落 `approvals` 表 |

**一致性边界**：决议状态（`approvals`）、`approval.resolved`、拒绝/超时的
`run.failed` 现在写在**同一事务**里（存储层 `resolve(on_resolved=...)` 回调，
[ADR-0016](decisions/0016-approval-decision-transaction.md)），不会再出现
「审批已完成但没有终态事件」。审批通过后的**恢复执行**仍在决议提交之后逐条追加
`act → verify → finalize` 事件：进程若在工具执行后、事件落库前崩溃，run 仍可能停在
非终态。当前不自动重试写工具（重试 = 可能重复开单），由运维按 run_id 对账/重放。

**反模式**（面试会问"这样设计有什么问题"）：
- 让模型自己判断"这个操作安全"→ 模型可被提示词注入影响
- 把审批做成"再问模型一次" → 等于没审批
- 审批记录只存"已通过"，不存参数快照 → 出问题无法复盘

## 8. MCP 落地

### 8.1 为什么用 MCP

- 2026 年事实标准，客户端/服务端可分离（未来可挂到任何 Host）
- 和 **LSP 同构**：都是 JSON-RPC，都有 `initialize` 握手、capability 协商、notification 流
  → 你做过 LSP 客户端，理解 MCP 只需一天

### 8.2 结构

```
app/tools/
├─ registry.py        # ToolSpec + ToolRegistry + ToolGuard（治理核心）
├─ servers/
│  ├─ cmdb.py         # FastMCP server: query_cmdb
│  ├─ tickets.py      # query_tickets, create_ticket
│  ├─ kb.py           # search_kb
│  └─ diagnostic.py   # run_diagnostic
└─ client.py          # MCP 客户端（stdio / streamable-http）
```

两种部署形态：

| 形态 | 传输 | 场景 |
|---|---|---|
| 同进程 | 直接函数调用（绕过 RPC） | 开发、单机私有化 |
| 独立进程 | stdio | 工具需要独立依赖/权限边界 |
| 远程服务 | streamable HTTP | 对接客户真实系统 |

> 治理逻辑放在 `registry.py`，**不在 MCP server 里**。这样换传输方式时治理不重复实现。

### 8.3 工具清单（v1）

| 工具 | 读/写 | 超时 | 角色 | 说明 |
|---|---|---|---|---|
| `query_cmdb` | 读 | 2000ms | 所有 | 按 owner / 资产号查设备信息 |
| `query_tickets` | 读 | 2000ms | 所有 | 查该用户历史工单 |
| `search_kb` | 读 | 1500ms | 所有 | 知识库混合检索 |
| `run_diagnostic` | 读 | 10000ms | it_support | 只读检测（ping/端口/驱动版本） |
| `create_ticket` | **写** | 3000ms | 所有（需审批） | 创建工单 |

> `create_ticket` 在 W3 D14 接通审批后真正落 `tickets` 表（`server/app/tools/tickets.py`），
> requester 由治理层注入；`query_cmdb` 仍是进程内假数据，后续接真实 CMDB 时只替换
> handler 与 `input_schema`，`ToolGuard` 不改（R3）。
> 清单里的 `query_tickets` / `search_kb` / `run_diagnostic` 尚未注册：`search_kb`
> 当前是 `retrieve` 节点（不是工具），另两个随接真实系统时再加，避免先写假工具
> 再改一遍治理用例。

## 9. 审计与可观测

每次工具调用写一条：

```json
{
  "run_id": "...", "call_id": "call_3", "tool": "create_ticket",
  "user_id": "u_102", "roles": ["employee"],
  "decision": "requires_approval",
  "args_hash": "sha256:...",
  "status": "ok", "duration_ms": 412, "retries": 0,
  "approval_id": "apr_9f..."
}
```

用途：回答"这个功能上线后有没有人越权试过"——这类问题在企业交付里一定会被问。

## 10. 面试高频追问与答法

| 问题 | 答法要点 |
|---|---|
| 工具调用超时怎么办？ | 按工具配超时 + 协作式取消（handler 内部要响应 CancelledError）+ 上层兜底 + 按错误类型决定重试 + 指数退避带抖动 |
| 模型能不能直接写库？ | 不能。权限/写库/金额/审批四类永远走业务代码，模型只给意图和参数 |
| 模型在 args 里塞 user_id 怎么办？ | 保留字段黑名单，直接拒绝并告警；身份只由服务端会话注入 |
| 一个工具挂了会影响整个 run 吗？ | 不会，单工具失败记 error 继续，verify 决定是否继续/重规划 |
| 审批是不是形式主义？ | 不是——审批把执行权交还给人；模型不能自己批准自己；审批记录含参数快照可用于复盘 |
| 怎么测越权？ | 20 条构造用例（伪造角色、注入指令、越权参数），CI 里跑，必须 100% 拦截 |
