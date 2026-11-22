# ADR-0114：工具配置回滚使用独立来源值

## 背景

ADR-0112 的回滚会追加一条新的 `tool_setting_changes` 记录，但来源沿用
`source="tool"`，与普通「管理页 PATCH 启用开关」无法区分。ADR-0113 的待定项也提到
是否给回滚独立 `source`。管理员按来源审计时，无法只看回滚，或把回滚排除在手动变更之外。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 继续复用 `source="tool"` | 不需要改任何东西，但回滚与手工 PATCH 永久混在一起 |
| 增加 `is_rollback` 布尔列 | 语义直观，但要迁移、改两套 store 与 CSV/前端，且与来源字段重复 |
| 复用 `source` 增加 `"rollback"`（采用） | 无迁移；`source` 已是 String(16)，现有查询/CSV/前端过滤可复用 |
| 用 `before`/`after` 推断回滚 | 不可靠：手工 PATCH 也可能把配置改成某个历史快照 |

## 决策

1. `POST /admin/tools/{name}/history/{change_id}/rollback` 追加的新记录使用
   `source="rollback"`；普通 PATCH 仍写 `source="tool"`，权限矩阵保存仍写 `source="matrix"`。
2. `/admin/tools/{name}/history` 与 `/history/export` 的 `source` 枚举扩展为
   `tool|matrix|rollback`；游标指纹随筛选值变化，跨来源复用旧游标仍 400。
3. 已有历史中的回滚记录保持 `source="tool"`，**不回填**；无法从旧数据可靠区分。
4. 不新增表、列或 CHECK；`tool_setting_changes.source` 当前是 `String(16)`，足以容纳。
5. 前端历史筛选来源增加「回滚」，历史行来源标签显示「回滚」；导出沿用同一筛选。

## 后果

- 新回滚记录可按来源单独筛选/导出；旧回滚记录仍归在「管理页」。
- 管理页来源选项从 2 种变 3 种；CSV `source` 列直接带 `rollback`，下游无需新列。
- 没有新迁移；`source` 仍是无数据库枚举约束的字符串，新增来源值不需要 DDL。
- 回滚仍会追加记录、不修改旧记录；`before`/`after` 语义不变。

## 验证

- `server/tests/test_tool_history.py`：回滚后断言新记录 `source == "rollback"`；按
  `source=rollback` 查询只返回该记录，`total == 1`；原 `source="tool"` 用例仍通过。
- `web/src/api/tools.test.ts`：`source=rollback` 列表/导出 URL 参数正确。
- 后端 18 passed；前端 31 files/157 tests、`tsc`、`oxlint`、`oxfmt --check`、`build` 通过。
- 后端默认 537+42 / PG 576+3 / PG+Redis 579；无新迁移。

## 待定

- 是否在历史行把「回滚来源」显示成独立图标；当前只用文案「回滚」。
- 是否为旧回滚记录做一次性人工标记；不做自动推断。
