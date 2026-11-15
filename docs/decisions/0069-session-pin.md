# 0069 会话置顶

## 背景

会话列表按最近一次活动倒序（ADR-0030 / ADR-0033），常用会话一旦几天没有新 run 就会沉到
列表深处。用户需要把「常看的故障群」「长期跟进的项目」固定在侧栏顶部，而不是每次搜索或
翻页。ADR-0030 与 ADR-0040 的待定项都记着「置顶会话」，本 ADR 补这一项。

置顶是**每个用户自己的列表偏好**，不改变会话内容、权限或其他用户的视图；也不能绕过
ADR-0019 的文档级可见性。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 只在前端 `localStorage` 记住置顶 | 否决 | 换设备/浏览器丢失；服务端分页与搜索无法按置顶排序，翻页会出现顺序断裂 |
| 给 `runs` 或 `session_titles` 加 `pinned` 列 | 否决 | 一个会话可能有多条 run，且置顶是用户维度，不是会话维度；会写坏投影 |
| 只允许置顶当前打开的会话 | 否决 | 置顶动作通常发生在列表里；强制打开再置顶多一步，且不解决批量整理 |
| 用 `pinned_at` 作为置顶组内排序 | 否决 | 置顶组内仍应按最近活动排，才能和用户对「最近」的直觉一致；`pinned_at` 只用于审计/排错 |
| 独立 `pinned_sessions` 表，主键 `(user_id, session_id)` | **采纳** | per-user、天然幂等、与 `hidden_sessions`/`session_titles` 同构；不污染 run 投影 |

## 决策

1. **新表 `pinned_sessions`**，复合主键 `(user_id, session_id)`，字段 `pinned_at`；
   无外键、无额外索引（主键即点查）。迁移 `0021`。

2. **`SessionSummary` 增加 `pinned: bool`**；`GET /sessions` 排序改为
   `(pinned DESC, updated_at DESC, session_id DESC)`。置顶组内仍按最近活动排；
   `pinned_at` 不参与排序。按标题搜索 `q` 同样先置顶、再按活动排序。

3. **游标扩展为 `{t, s, p}`**：`p` 表示「是否在置顶段」。旧游标只有
   `{t, s}`，升级前一定处在非置顶段，因此解码时缺 `p` 按 `false` 处理；
   取满时编码最后一条的 `pinned`。非法游标仍返回 `400 INVALID_CURSOR`。

4. **置顶/取消置顶接口幂等**：

   ```http
   POST   /api/sessions/{session_id}/pin
   DELETE /api/sessions/{session_id}/pin
   ```

   成功均返回 `204 No Content`。重复置顶/重复取消仍 204；别人的会话、不存在的会话、
   已从列表移除的会话都返回 `404 {"detail":"session not found"}`，不泄露存在性。

5. **隐藏会话时同事务删除置顶行**：`DELETE /sessions/{session_id}` 仍然只做软移除，
   但同一事务里清掉 `pinned_sessions` 行。恢复会话时也会同事务清掉该会话的置顶行，
   作为并发隐藏/置顶的兜底；恢复后不恢复置顶——用户重新决定是否置顶。
   这样不会出现「已移除列表里藏着一个置顶项」的悬挂状态。

6. **置顶只校验「本人可见」**：必须存在至少一条该用户的 run，且该会话未被
   `hidden_sessions` 移除；不要求 run 未过期，也不读取正文。

7. **前端按字段存在性渐进增强**：`SessionSummary.pinned` 是可选的布尔值。旧后端不返回
   该字段时，不渲染置顶按钮（避免滚动升级期间点击 404）；新后端返回 `pinned` 后，
   行内显示 Pin 按钮，`aria-pressed` 表示当前状态，请求在途时禁用同一行。
   成功后重新拉第一页列表；失败只提示，不改本地顺序。

8. **无迁移回填**：置顶从用户第一次点击开始；已有会话默认都不置顶。

## 后果

- 常用会话真正固定在顶部，搜索与分页仍保持同一排序，不会出现「第二页又冒出一个置顶」。
- 置顶组内按最近活动排，最近置顶的旧会话不一定排第一；这是为了与普通列表的「最近」
  语义一致，接受的取舍。
- 置顶数量不设上限；极端情况下用户可以把所有会话置顶，此时列表退化为普通活动排序。
- 已隐藏会话不保留置顶；恢复后需要重新置顶。前端必须在移除时清掉行内状态。
- 滚动升级期间，新前端 + 旧后端会隐藏置顶按钮；旧前端 + 新后端会忽略多出来的
  `pinned` 字段，列表/游标仍可读（旧前端不解析 `p`，但也不会用 `p` 翻页）。
- 不改变 `updated_at`，置顶/取消置顶不会把会话标成「最近活动」。

## 验证

- `server/tests/test_store_contract.py::_exercise_pinned_sessions`：置顶顺序、`pinned`
  标志、跨置顶边界的三段游标、旧两段游标兼容、隐藏清置顶、恢复清置顶、
  重复置顶/取消幂等、别人/不存在的会话返回 `False`。
- `server/tests/test_sessions_api.py::test_sessions_pin_and_legacy_cursor`：204、列表排序、
  `pinned` 字段、三段游标翻页、取消置顶、隐藏后置顶 404、恢复后未置顶、别人的会话 404、
  旧两段游标。
- 默认 `pytest`：**503 passed + 40 skipped**；Postgres：**540 passed + 3 skipped**；
  Postgres + Redis：**543 passed**。
- `ruff check` / `ruff format --check`（196 files）/ `mypy app`（114 files）通过。
- 前端：**87 tests / 18 files**、`tsc --noEmit`、`oxlint` 0/0（73 files）、
  `oxfmt --check` 81 files、`pnpm build` 通过。
- 迁移 `0021`：`upgrade head` → `alembic check`（No new upgrade operations detected）→
  `downgrade 0020` → `upgrade head` 往返通过。

## 待定

- 置顶组的拖拽排序 / 自定义顺序（当前组内按最近活动）。
- 置顶数量上限与「置顶太多」的提示。
- 批量置顶/取消置顶。
- 置顶操作审计（谁在何时置顶了哪个会话）。
- 恢复已移除会话时恢复原置顶状态（当前刻意不恢复）。
