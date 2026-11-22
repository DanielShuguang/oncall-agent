# ADR-0112：工具配置变更历史支持回滚

## 背景

ADR-0037 把每次工具配置变更的 `before` / `after` 存进 `tool_setting_changes`，
管理页只能看历史。线上把某个工具误禁用、或矩阵保存把角色改错时，管理员只能手工
根据历史重建一份配置再 PATCH / 整表保存；`before` 里已有的信息没有入口直接用。

历史本身不可修改：删掉记录等于抹掉审计。回滚应产生一条**新的**变更记录，而不是
改写旧记录。

## 备选方案

| 方案 | 结论 |
|---|---|
| 删除目标历史行后重放 | 拒绝：破坏审计，且无法证明删除前是什么 |
| 只回滚 `enabled`，角色继续手工 | 拒绝：矩阵改错时仍无法恢复，和「回滚一条变更」名不符 |
| 新增 `rolled_back` 标记或独立回滚表 | 拒绝：回滚本质上就是一次普通配置写入，额外状态会分叉 |
| 读取历史 `before` 快照并写回（采纳） | 一次写入、复用现有历史/权限/缓存失效路径 |

## 决策

1. 新增 `POST /api/admin/tools/{name}/history/{change_id}/rollback`，管理员角色；
   工具必须仍在代码注册表中，否则 404 `TOOL_NOT_FOUND`。
2. `change_id` 必须属于该工具；不存在返回 404 `HISTORY_NOT_FOUND`。
3. 回滚目标是该条历史的 `before` 快照：
   - `before = null`：删除 `tool_settings` 覆盖，回到代码默认；
   - `before = {enabled, roles}`：重建 `ToolOverride`，角色 `[]` 表示所有登录用户。
4. 代码中已禁用的工具不能被回滚开启（`enabled=true` 且 `spec.enabled=false` 时
   422 `TOOL_LOCKED`），与 PATCH 的硬边界一致。
5. 当前配置已经等于目标时不写新记录，只返回当前生效配置；幂等重试不会污染历史。
6. 真正变化时，在 `tool_settings` 写入的同一事务追加一条普通工具变更记录：
   `source="tool"`，`before` 是回滚前配置，`after` 是目标快照，`changed_by` 是当前
   管理员。不新增 `rollback` source、不新增迁移。
7. 回滚矩阵保存产生的某条历史时，只恢复该行的单个工具快照，不重放整次矩阵提交。
8. 前端历史 Dialog 每条记录提供「回滚」按钮，确认后调用接口，并刷新工具列表与
   当前历史；回滚结果以新记录的形式出现，不隐藏原记录。

## 后果

- 回滚会产生新历史行，历史只增不减；可以连续回滚到更早的状态。
- 回滚无法恢复已被删除的工具（代码注册表是硬边界），也无法撤销下载审计等副作用。
- 回滚的并发语义与普通管理写入相同：last-write-wins，`before` 是执行瞬间读到的
  当前配置，不保证接上被回滚记录的 `after`。
- 不支持批量回滚、差异预览、回滚到任意时间点；这些留在待定。
- 无需新表/新索引；`tool_setting_changes` 的既有索引足够。

## 验证

- `tests/test_tool_history.py`：回滚恢复 `before=null`；新历史行是
  `before={enabled:false, roles:null}`、`after=null`；重复回滚同一 id 不新增记录；
  未知 id 404、员工 403。
- `tests/test_tool_history_pg.py`：PG store 的 `get_history` 单条查询与不存在场景。
- 默认 `pytest` **537 passed + 42 skipped**；PG-only **576 passed + 3 skipped**；
  PG+Redis **579 passed**。
- `ruff check` / `ruff format --check` 210 files / `mypy app` 119 files 通过。
- 前端 30 files / 153 tests、`tsc`、`oxlint`、`oxfmt --check`、`pnpm build` 通过。

## 待定

- 是否支持一次回滚整次矩阵提交（需要 batch id）。
- 回滚前是否展示「当前 → 目标」差异预览。
- 是否给回滚单独加 `source="rollback"` 以方便筛选；当前复用 `tool`，靠 `before/after`
  与操作人识别。
