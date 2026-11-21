# ADR-0103：工具历史游标过期后的原地重新加载

## 背景

ADR-0102 给工具配置变更历史游标加了 1 小时有效期：过期返回 `400 CURSOR_EXPIRED`，
`useToolHistory` 把错误放在 `loadMoreError`，已加载列表保留。但 UI 只显示一行错误；
用户要关掉 Dialog、重新打开历史，才能回到第一页。ADR-0102 的「待定」明确把
「在 Dialog 内提供重新加载快捷按钮」列为候选。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 只显示错误，要求关闭重开 | 实现最小；多一步操作，且用户可能误以为整个弹窗坏了 |
| 自动重放第一页 | 用户可能正在读旧列表，自动替换会打断；与 ADR-0102 决策 6「不自动重放」冲突 |
| 对任意「加载更多」错误都显示重新加载 | 网络错误/403 也可能出现，重载同样可能失败；语义不精确 |
| 仅对 `CURSOR_EXPIRED` 显示「重新加载」（采纳） | 错误码明确，用户知道自己按了什么；不改变其他错误处理 |

## 决策

1. `ApiError` 增加可选 `code: string | null`；`toApiError` 继续原样保留 `message`，额外
   解析后端统一错误体里的 `code`。没有 `code` 的旧错误（401、网关 502、非 JSON）保持
   `null`，现有调用方不需要改。
2. `HistoryState` 增加 `loadMoreErrorCode: string | null`；`useToolHistory` 在
   「加载更多」失败时记录 `ApiError.code`，其他异常为 `null`。成功/开始新请求时清空。
3. 只有 `loadMoreErrorCode === 'CURSOR_EXPIRED'` 时，在错误行旁显示「重新加载」按钮；
   其他错误仍只显示消息，不提供误导性的重试。
4. 「重新加载」用**已应用**筛选（`appliedFrom/appliedTo/appliedBy/appliedSource`）重新取
   第一页，不使用尚未应用的草稿。这样不会把「用户还没点应用」的筛选偷偷生效；代价是
   草稿会被重置为已应用值，属于可接受的明确行为。
5. 不自动重放；不在后端新增接口；无迁移。后端错误码与 TTL 仍由 ADR-0102 决定。
6. 日期草稿校验失败（单端/倒置）时同时清空 `loadMoreError`/`loadMoreErrorCode`，避免旧的
   「游标已过期」提示与新的日期校验错误同时挂在 Dialog 里。

## 后果

- 过期后用户一次点击即可恢复当前视图，不必关闭 Dialog。
- 草稿中尚未应用的筛选在点「重新加载」后会回到已应用值；按钮只出现在游标过期时，
  用户能预期这是「重置到第一页」。
- `ApiError.code` 是通用能力，后续其他需要按错误码分支的页面可以直接复用；可选字段
  保证旧构造方式仍可编译。
- 前端多两个 client 测试；后端无改动。

## 验证

- `web/src/api/client.test.ts`：`{code:"CURSOR_EXPIRED"}` 透传为 `ApiError.code`；无 code
  的 403 仍为 `null`。
- `web/src/features/console/useToolHistory.ts`：加载更多失败记录 `loadMoreErrorCode`，
  `reloadExpiredHistory` 使用已应用筛选重新请求第一页。
- `ToolsDialogs` 只在 `CURSOR_EXPIRED` 时渲染「重新加载」。
- 前端 27 files / 140 tests、`oxlint` 0/0（133 files）、`oxfmt --check` 141 files、
  `pnpm build` 通过；后端沿用 533+42 / 572+3 / 575，无迁移。

## 待定

- 是否把「重新加载」也用于 `INVALID_CURSOR`（目前该错误多由筛选切换/旧版本引起，重载
  同样可能失败，先不混在一起）。
- 是否在重新加载前二次确认会丢弃未应用草稿；当前只重置草稿，不弹确认。
