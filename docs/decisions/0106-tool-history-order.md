# ADR-0106：工具配置变更历史双向排序（最新/最早）

## 背景

ADR-0100 把工具配置变更历史改成了 keyset 分页，但只支持从新到旧加载，并在「待定」里
明确留了「是否需要跳到最早/最新」。实际审计时经常需要先看某个窗口里最早的一次变更，
确认「最初是谁改的」；只能一路「加载更多」翻到最旧，窗口有几千条时不可用。

## 备选方案

| 方案 | 结论 |
| --- | --- |
| 前端缓存全部页再反转 | 不采纳：内存与请求都不可控，且总数/新写入会漂移 |
| 加 `offset` / 页码 | 不采纳：与 ADR-0100 的 keyset 契约冲突，深页仍慢 |
| 两个独立端点 | 不采纳：过滤、总数、游标校验要复制两份，容易漂移 |
| **同一端点加 `order`** | **采纳**：复用同一窗口/过滤/计数，只是比较方向与排序方向不同 |

## 决策

1. `GET /admin/tools/{name}/history` 与 `/history/export` 增加 `order`，取值
   `latest`（默认）/ `earliest`。
2. `latest` 继续用 `(changed_at, id) < before` 倒序；`earliest` 用
   `(changed_at, id) > after` 升序，只比较这两个字段，不做 `OFFSET`。
3. 游标指纹纳入 `order`：同一个游标从 `latest` 换到 `earliest`（或反向）返回
   `400 INVALID_CURSOR`；游标本身仍只存 `(t, i, f, e)`，不额外存排序。
4. `total` 仍只在第一页返回，`has_more` 与「取满才给 `next_cursor`」语义不变；
   `earliest` 的 `next_cursor` 取当前页最后一条（时间最大的一条）。
5. 导出与列表使用同一 `order`；导出审计的 `filters` 只在 `earliest` 时附加
   `order=earliest`，默认 `latest` 不写入，保持旧审计记录的字段形状。
6. 前端历史 Dialog 增加「最新在前 / 最早在前」下拉；应用后才改变列表，加载更多与
   导出都使用已应用的 `order`；切换排序清空旧游标。
7. 不做页码/跳页、按行号增量、游标签名；没有迁移。

## 后果

- 审计员可以在同一窗口直接看最早/最新，不需要把中间页全部读一遍。
- 新参数只影响 `order=earliest`；旧前端不传时新请求行为完全不变。游标指纹新增 `order` 后，部署前签发的在途游标会因指纹不匹配失效一次（`400 INVALID_CURSOR`），刷新/重开历史即恢复；这是升级窗口的已知影响。
- 升序翻页仍受 1 小时游标 TTL 限制（ADR-0102/0105），长时间停在最早一页后继续翻页
  需要重新加载，这是有意的。
- 索引仍是 `(tool_name, changed_at DESC)`；升序查询可以反向扫描，不新增索引。

## 验证

- 默认 `pytest`：**534 passed + 42 skipped**
- PG-only：**573 passed + 3 skipped**
- PG+Redis：**576 passed**
- `ruff check` / `ruff format --check` 208 files / `mypy app` 119 files 通过
- 前端 **28 files / 146 tests**、oxlint 0/0（136 files）、oxfmt 144 files、
  `pnpm build` 2942 modules 通过
- 迁移：无（仍 0026）

## 待定

- 是否在 UI 上提供「跳到最新/最早」按钮（当前是下拉切换）；
- 升序下是否也需要「回到最新」的快捷入口；
- 是否把 `order` 持久化到本地偏好（当前不持久化）。
