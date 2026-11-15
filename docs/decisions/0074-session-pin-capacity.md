# ADR-0074：置顶容量提示

- 状态：已采纳
- 日期：2026-11-15
- 相关：[ADR-0069](0069-session-pin.md)、[ADR-0073](0073-session-pin-limit.md)

## 背景

ADR-0073 给每个用户加了 50 个置顶的硬上限：第 51 个 `POST /sessions/{id}/pin`
返回 `409 PIN_LIMIT_REACHED`。但前端在点击前不知道当前已经置顶了多少个，只能让
用户先点、再看到错误。对“整理常用会话”这种连续操作，体验是多一次失败往返。

ADR-0073 的待定项已经写了「达到上限时是否在置顶按钮上提前禁用（需要列表返回
计数或用户信息）」。本 ADR 补这一项。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 前端硬编码 50 | 否决 | 上限一旦调整，前端与后端悄悄漂移 |
| 新增 `GET /sessions/pins` 计数接口 | 否决 | 列表页每次刷新多一次请求，且要维护独立 loading/error |
| 只在 `409` 响应里返回当前计数 | 否决 | 仍然是失败后才知道，不能提前禁用 |
| 在 `GET /sessions` 附带 `pinned_count` + `pin_limit` | **采纳** | 列表本来就要查，前端一次拿到容量；无新表/迁移 |
| 仅在首屏返回、后续页 `null` | 否决 | 加载更多时前端要额外保存状态；每页多一次 count 成本很低 |
| 管理员可配置上限 | 暂缓 | 当前是产品常量，配置化需要租户/策略设计 |

## 决策

1. `GET /sessions` 的每一页响应增加 `pinned_count` 与 `pin_limit`：
   - `pinned_count` 是当前用户**全部**置顶数，不受 `q` 与游标影响；
   - `pin_limit` 是服务端常量 `MAX_PINNED_SESSIONS`，避免前端硬编码。
2. `RunStore.count_pinned_sessions(*, user_id)` 由内存/PG 两个实现提供；PG 用
   `count(*) where user_id = ?`，复用 `pinned_sessions` 主键前缀。PG 的隐藏与置顶
   共用同一用户级 advisory lock，隐藏后计数不会保留不可取消的残留置顶行。
3. 计数与列表在同一个 `try` 中；任一数据库故障仍返回 503，不返回半截列表。
4. 前端 `SessionSummary` 不变，`SessionPage` 增加两个可选字段：
   - 旧后端没有字段时 `pinnedCount`/`pinLimit` 保持 `null`，不提前禁用；
   - `pinnedCount >= pinLimit` 时，未置顶行的置顶按钮 `disabled` 并带
     `title="置顶数量已达上限（50 个）"`；已置顶行仍可取消。
5. 置顶/取消后仍刷新列表，计数随响应更新；不维护第二份本地计数。
6. 无迁移、无新索引；上限仍固定 50。

## 后果

- 每次会话列表请求多一次 `count(*)`；`pinned_sessions` 以 `(user_id, session_id)`
  为主键，计数走主键前缀，成本可控。
- 列表返回的是请求时刻的计数，用户在多标签页/并发下仍可能看到“49 个”后点出
  409；409 仍是最终兜底。
- `pin_limit` 是服务端常量，不是租户策略；多副本升级期间新旧字段并存时，旧前端
  忽略新字段，新前端在旧后端上回退到 409。
- 达到上限后按钮禁用，用户不必再点一次才知道；没有独立的“容量页面”。

## 验证

- `server/tests/test_store_contract.py`：置顶 2 个后 `count_pinned_sessions` 为 2，
  取消后为 0，隐藏已置顶会话后回到 0；内存与 PG 契约同跑。
- `server/tests/test_sessions_api.py`：`GET /sessions` 的 `pinned_count` 1→2→1、
  `pin_limit=50`；空结果同样带计数；列表失败与计数失败都 503。
- 前端 `SessionPage` 可选字段 + `SessionList` 的 `pinLimitReached` 禁用逻辑；无组件
  单测，沿用 `tsc`/`vitest`/`oxlint`/`oxfmt`/`pnpm build`。
- 默认 `pytest`：**506 passed + 40 skipped**；Postgres：**543 passed + 3 skipped**；
  Postgres + Redis：**546 passed**；`ruff check`/`ruff format --check` 196 files、
  `mypy app` 114 files；前端 **94 tests / 19 files**。

## 待定

- `pinned_count` 是否在 409 响应里也返回，方便旧前端。
- 上限改为环境变量/租户策略。
- 置顶操作审计（谁在何时置顶/取消置顶）。
- 置顶组的拖拽排序/自定义顺序。
- 批量置顶/取消置顶。
