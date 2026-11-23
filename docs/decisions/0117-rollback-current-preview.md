# ADR-0117：回滚预览读取执行瞬间的当前配置

## 背景

ADR-0113 的确认 Dialog 展示的是「记录时的变更后快照」（`change.after`）与「回滚目标」
（`change.before`），并用一段文字说明实际写入的 `before` 是执行瞬间的当前配置。管理员看不到
当前值，无法判断配置是否在打开历史后被其他管理员改过；保留在待定项里。

## 备选方案

| 方案 | 结论 |
|---|---|
| 继续只用文字说明 | 不采纳；差异正是管理员需要核对的信息 |
| 前端用最后一次工具列表快照 | 不采纳；列表可能过期，且打开 Dialog 时没有重新读取 |
| 新增只读预览接口 | 采纳；服务端在打开 Dialog 时读一次当前覆盖 |
| 预览接口同时加库/缓存 | 不采纳；一次管理页操作的读放大没有收益 |

## 决策

1. 新增 `GET /admin/tools/{name}/history/{change_id}/preview`，仅管理员可访问。
2. 返回：
   - `current`：预览时读到的当前覆盖，`null` 表示没有覆盖、走代码默认；
   - `target`：该条历史 `before` 还原出的目标覆盖，`null` 表示删除覆盖；
   - `changed`：`current != target`，相同则回滚不会追加历史；
   - `rollbackable` / `reason`：代码中已禁用的工具不能通过回滚开启，预览阶段返回
     `rollbackable=false` 与原因，而不是 422；执行阶段仍返回 422 `TOOL_LOCKED`。
3. 预览是只读操作：不写历史、不写审计、不改配置；库不可用返回 503。
4. Dialog 打开时请求预览；读取中、读取失败、`changed=false` 或 `rollbackable=false`
   时禁用「确认回滚」。取消不产生任何请求副作用。
5. 执行回滚时服务端仍重新读取当前配置并以那时为准；预览与执行之间可能被其他管理员
   改动，因此预览是建议值，不是 CAS 或锁。
6. 不新增表/迁移；不改变回滚请求/响应契约。

## 后果

- 每次打开回滚确认多一次只读查询，换来当前值可见与代码禁用工具的提前提示。
- 预览与执行之间仍可能漂移；Dialog 文案明确「以执行时为准」，不承诺快照一致。
- 预览本身不写下载审计；它不产生文件。

## 验证

- `server/tests/test_tool_history.py`：回滚前预览返回 `current/target/changed/rollbackable`；
  回滚后同一预览 `changed=false`；未知工具 404 `TOOL_NOT_FOUND`、未知历史 404
  `HISTORY_NOT_FOUND`、员工 403。
- `web/src/api/tools.test.ts`：预览 GET 路径。
- 前端 `pnpm test` 32 files/162 tests、`tsc`、`oxlint` 0/0（145 files）、`oxfmt --check`
  153 files、`pnpm build` 2947 modules；后端默认 537+42、PG-only 576+3、PG+Redis 579；
  ruff 210 / format 210 / mypy 119。

## 待定

- 是否在预览响应里附带工具代码默认值（当前 `current=null` 只表示没有覆盖，前端仍从列表
  读取 `code_enabled`）。
- 是否支持批量预览多条历史；当前只按单条历史记录预览。
