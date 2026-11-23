# ADR-0120：回滚预览附带工具代码默认配置

- 状态：已采纳
- 日期：2026-11-23
- 相关：ADR-0117、ADR-0112、ADR-0113

## 背景

ADR-0117 的回滚预览返回 `current`、`target` 和 `changed`，其中 `current=null` 表示「没有覆盖、走代码默认」。
但界面只能看到这个 `null`，看不到工具代码里实际的默认启用状态和默认角色；管理员无法判断
`current=null` 时到底是谁能调用、是否启用，容易把「继承默认」误读成「禁用/无人可用」。

ADR-0117 的待定项已经记录了这一点：是否在预览响应里附带工具代码默认值。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 前端从工具列表的 `effective_enabled`/`effective_roles` 推断 | 不采纳；工具列表和预览是两次请求，列表可能已过期，且预览应自包含 |
| 只在 `current=null` 时额外请求一次 `/admin/tools` | 不采纳；多一次读、多一次竞态，字段仍分散 |
| 预览响应直接附 `code_default` | **采纳**；一次请求自包含，界面可解释 `current=null` |

## 决策

1. `ToolRollbackPreviewOut` 增加必填 `code_default`，结构复用 `ToolOverrideSnapshot`：
   `enabled` 为代码 `ToolSpec.enabled`，`roles` 为代码 `ToolSpec.roles` 的列表（`[]` 表示所有登录用户）。
2. 预览接口始终返回代码默认，即使 `current` 有覆盖也不省略，便于对照。
3. 前端回滚 Dialog 增加「代码默认配置」行；`current=null` 时显示「无覆盖，按代码默认生效」，
   不再只显示一个容易误读的「代码默认」。
4. 只读语义不变：`code_default` 只来自已注册的 `ToolSpec`，不查库、不写历史/审计。
5. 回滚执行仍重新读取当前配置；`code_default` 只用于确认预览时的解释，不作为执行依据。

## 后果

- 预览响应更大一点（两个字段），但管理员能看清「无覆盖时到底启用给谁」。
- 工具代码默认改变后，旧预览不会自动更新；重新打开预览即可看到新的 `code_default`。
- 如果工具未注册，仍返回 `404 TOOL_NOT_FOUND`，不会返回默认值。

## 验证

- `server/tests/test_tool_history.py` 的回滚预览断言增加
  `code_default == {"enabled": true, "roles": []}`（`query_cmdb` 代码默认启用、所有登录用户）。
- 前端 `RollbackPreviewDialog` 展示代码默认与无覆盖提示；现有预览测试继续通过。
- 默认/PG/PG+Redis 与 ruff/format/mypy 沿用 ADR-0117 基线，本次不改迁移。

## 待定

- 是否进一步展示「当前生效值」（覆盖优先、代码默认兜底）的单一字段；目前由 `current` 与
  `code_default` 两行组合表达。
- 是否在回滚执行响应里返回同样的预览快照，便于前端直接更新；当前仍以执行结果重读列表。
