# ADR-0091：置顶审计日期快捷预设

- 状态：已采纳
- 日期：2026-11-17
- 相关：ADR-0071（恢复审计日期预设）、ADR-0085（置顶审计管理页）、ADR-0086（置顶审计日期范围）

## 背景

恢复审计管理页有五个 UTC 日期快捷预设（ADR-0071），置顶审计管理页只有
`开始（UTC）`/`结束（UTC）` 两个日期输入。管理员查「最近 7 天谁取消过置顶」时，
要手工算日期再点筛选，和恢复审计页的操作不一致。

ADR-0086 当时明确「不做快捷预设」，因为日期范围本身已经可用；但管理页已经
有置顶审计的统计、列表与导出，快捷预设是纯前端交互，不改变查询契约，是这一轮
可以独立闭环的缺口。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 复用恢复审计页的预设存储 `oncall.audit-date-preset.v1` | 两个页面的过滤条件不同；在置顶页点「近 7 天」会改掉恢复审计页下次打开的默认，跨页耦合 |
| 单独持久化置顶页预设 | 需要新 key、版本与清理策略；置顶页当前不持久化任何过滤，单独记住日期反而制造「为什么只记日期」的不一致 |
| 只做按钮、不持久化 | 点一下立即生效，刷新后回到空筛选；行为可解释，改动最小 |
| 前端计算日期但等用户再点「筛选」 | 多一步；预设的预期就是「一键切窗口」 |

## 决策

1. **复用 `auditDatePresets.ts` 的 `AUDIT_DATE_PRESETS` 与 `auditDatePresetRange`**，
   不复制日期算法；五个预设仍为近 7/30/90 天、本月、上月，按 UTC 自然日闭区间。
2. **点预设立即应用**：`PinAuditPage` 把预设区间写入草稿，并调用与「筛选」相同的
   `commitFilters(nextDraft)`，一次完成列表清空、统计清空、导出失效与请求。
   不要求用户再点一次「筛选」。
3. **不持久化**：不读写 `oncall.audit-date-preset.v1`，也不新增 key。刷新/重新进入
   页面回到空筛选；需要保留时用户仍可看当前 URL 之外的页面状态，但不跨会话记忆。
4. **高亮由区间反推**：`activeAuditDatePreset(from, to)` 只在草稿区间与某个预设的
   当前 UTC 区间完全相等时返回该预设；手填日期不误高亮。比较不写回存储。
5. **筛选卡独立成文件**：`PinAuditFilterCard` 从 `PinAuditSections.tsx` 拆到
   `PinAuditFilterCard.tsx`，避免置顶页/分段文件超过 300 行；`PinAuditDraft` 与
   `EMPTY_PIN_AUDIT_DRAFT` 一并迁出。
6. **导出状态独立成 hook**：`usePinAuditExport` 承接导出中/成功/失败与竞态 token，
   页面只组合；行为与 ADR-0084/0090 一致。
7. **服务端校验不变**：预设生成的日期仍走原有 `days`/`created_from`/`created_to`
   校验（同时填写、最多 365 天、UTC）；前端不绕过，也不新增 API 参数。
8. **无迁移/无后端改动**：只改前端交互与组件边界。

## 后果

- 置顶审计页与恢复审计页的日期操作一致；常用窗口一键切换。
- 页面刷新不保留预设；这与置顶页其他过滤条件的行为一致，不引入第二套偏好存储。
- 预设按 UTC 计算；在 UTC 午夜前后点击可能得到与本地日历不同的「今天」，与后端
  的 UTC 日期范围口径一致。
- 手填日期与预设区间完全相同时会高亮对应预设；这是展示层的推断，不改变筛选值。
- `PinAuditFilterCard`/`usePinAuditExport` 新增两个文件，`PinAuditPage` 仍 ≤300 行；
  `PinAuditSections.tsx` 只保留列表卡。

## 验证

- 前端 `auditDatePresets.test.ts` 新增 `activeAuditDatePreset` 用例：精确匹配返回
  `last7`，差一天/空值返回 `null`；原有五个预设与存储用例保持通过。
- `PinAuditPage` 的预设点击、`commitFilters` 清空列表/统计/导出、`clearFilters`
  重置草稿均复用既有路径；导出 hook 的单测仍由 `pinAudits.test.ts` 覆盖请求参数。
- 实测：前端 `pnpm test` **26 files / 128 tests**、`tsc --noEmit`、`oxlint` 0/0
  （127 files/232 rules）、`oxfmt --check` 135 files、`pnpm build` 通过；
  后端未改，沿用默认 **517 passed + 40 skipped**、PG-only **554 passed + 3 skipped**、
  PG+Redis **557 passed**、`ruff check` / `ruff format --check` 200 files、
  `mypy app` 116 files。
- 本次无新迁移，未执行迁移往返；`0022` 保持不变。

## 待定

- 是否把预设选择持久化到置顶页（需要与恢复审计页的偏好隔离设计）；
- 自定义区间命名/保存；
- 统计卡图表化与下载审计（仍属 ADR-0090 的待定项）。
