# ADR-0035：历史会话的运行过程回放（工具与审批）

- 状态：已采纳
- 日期：2026-11-12
- 相关：[ADR-0021](0021-data-retention.md)（事件保留）、[ADR-0022](0022-run-content-visibility.md)（回答回收）、
  [ADR-0023](0023-run-content-retention.md)（正文保留）、[ADR-0030](0030-session-list.md)（会话列表）

## 背景

ADR-0030 把会话列表做出来了，但历史 transcript 只还原 `input` / `output`。刷新页面后，
这一轮调了什么工具、参数是什么、有没有走审批、最后批没批，全部看不到——用户只能看到
一句结论，回答「为什么这么答」时没有依据。实时对话里这些信息本来就在（ToolCard /
ApprovalCard 由 SSE 事件驱动），只是没有为历史消息保留读模型。

事件表里已经有完整记录（`tool.call` / `tool.result` / `approval.required` /
`approval.resolved`），按 ADR-0021 保留 180 天；为它再建一张投影表既重复又需要迁移。
难点不在存，而在**边界**：工具参数可能含用户数据，审批记录含审批人；回答被权限回收
或过保留期后，过程不应比正文活得更久。

## 备选方案

| 方案 | 否决原因 |
|---|---|
| 前端直接拉 `/runs/{id}/events` 重建 | 把原始事件（含审批人、内部 payload）全部暴露给前端；还要处理分页与事件清理，逻辑重复 |
| 新建 `run_timeline` 表 | 与事件表重复，多一次写入与迁移；事件清理后仍要同步清理 |
| 只回「调用了 N 次工具」 | 不足以解释参数与审批结果，等于没解决问题 |
| **服务端只读投影（采纳）** | 复用事件真相，响应收敛到少量字段，可见性与回答对齐 |

## 决策

1. **只投影四类事件**：`tool.call`、`tool.result`、`approval.required`、
   `approval.resolved`。步骤事件与 `message.delta` 不进入历史回放——前者是执行细节，
   后者是正文本身，已经通过 `output` 还原。
2. **按 id 合并**：`tool.call` 建卡（`status=running`），`tool.result` 按 `call_id`
   补状态/结果/错误/耗时/重试；`approval.required` 建卡（`status=pending`），
   `approval.resolved` 按 `approval_id` 补状态、决议时间与理由。孤儿结果/决议直接忽略，
   不造没有入参的假记录。
3. **不返回审批人身份**：`resolved_by` 与 `scope` 属于内部治理信息，历史回放不需要；
   审计仍以 `approvals` 决议行与管理员接口为准（ADR-0027）。
4. **跟随回答可见性**：`output` 缺失（失败/未完成）、`content_redacted`、
   `events_pruned_at` 非空或 `content_pruned_at` 非空时，`timeline` 为空且
   `timeline_available=false`——「过程不可用」不能被显示成「这轮没调工具」。
   没有可见回答时前端也不渲染「已过期」提示，避免把「正文被回收」说成保留期问题。
5. **条数上限**：最多 20 项，超出用 `timeline_truncated=true` 明示；读取事件上限 500 条，
   正常一轮远小于此。宁可截断并说明，也不静默丢。
6. **字段收敛**：`args` 只接受 dict（否则 `{}`）；`status` 缺失为 `unknown`；
   耗时/重试只接受非负整数（排除 bool）；`write` 只认布尔 `true`（字符串 `"false"`
   仍视为只读）；文本字段只接受字符串。事件 payload 可能来自旧版本或被手工写入，
   接口不能假设它一定合法。
7. **无迁移、无新表**：事件仍是唯一真相，保留清理逻辑不变；事件被清理后过程自然消失。
   前端用 `<details>` 默认折叠，参数/结果以 JSON 展示，审批卡显示状态与理由。
8. **只读**：历史过程不提供重试、批准、拒绝等操作；这些只属于当前会话的实时交互。

## 后果

- 详情接口多一次 `events_after` 查询（最多 500 条）。本 ADR 发布时历史会话是「每个 run 一次」，
  20 轮即 20 次；现已由 [ADR-0036](0036-session-detail-batch.md) 的批量详情接口合并为一次事件查询。
- `timeline` 的 `result` 可能较大（例如资产列表），本 ADR 只做 20 项截断；
  单条载荷已由 [ADR-0044](0044-timeline-payload-cap.md) 在读取侧限制为 4096 字符 + 预览。
- 审批人身份不展示，普通用户看不到「谁批的」；管理员仍可在审批页看到。
- 事件保留期与正文保留期是独立配置（正文不得短于事件，见 ADR-0023）。二者任一过期，
  过程即不可用；这比「正文没了过程还在」更保守。
- 前端只新增折叠区，不改变消息气泡与引用角标；移动端窄屏仍可展开，但 JSON 较长时
  需要滚动。

## 验证

- 后端默认 `uv run pytest`：**438 passed + 32 skipped**；真实 Postgres 下
  **467 passed + 3 skipped**，再加 Redis 为 **470 passed**；
  `ruff check` / `ruff format --check`（176 files）/ `mypy app`（106 files）通过。
- 前端 `pnpm exec tsc --noEmit`、`pnpm test`（**65 tests / 13 files**）、`oxlint`、
  `oxfmt --check`、`pnpm build` 通过。
- 新增 `server/tests/test_run_timeline.py` 4 条（合并/审批身份隐藏/孤儿与 pending/截断与脏
  payload）与 `server/tests/test_runs_api.py` 的回放、事件清理断言。
- 检索、提示词、多轮历史未改，未重跑 RAG 与多轮评测。

## 待定

- 历史会话打开时的批量详情接口：已由 [ADR-0036](0036-session-detail-batch.md) 兑现
  （一次返回一页 run 的正文、引用与运行过程）。
- 单条工具结果/参数的字节上限与折叠预览：已由 [ADR-0044](0044-timeline-payload-cap.md)
  兑现（读取侧 4096 字符上限 + 1024 字符预览，事件载荷不动）。
- 是否给管理员展示审批人（需要单独的管理员接口，不能污染普通详情）。
- 更早的事件清理策略：目前事件与正文同保留期，过程与正文一起消失。
- 运行过程的搜索/筛选（按工具名、状态）与耗时聚合。
