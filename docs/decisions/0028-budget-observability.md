# 0028 · 预算可观测性：账本快照与今日用量

- 状态：已采纳（W6 后加固）
- 日期：2026-11-11
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/07-frontend-design.md](../07-frontend-design.md)、[docs/09-deploy-private.md](../09-deploy-private.md)、[ADR-0013](0013-model-gateway.md)、[ADR-0026](0026-user-daily-budget.md)

## 背景

ADR-0026 把个人日预算做成了闸门，但它的两个「待定」指向同一件事：**花得对不对，看不见**。

1. **预扣泄漏没有出口。** 预算是乐观记账：先 `reserve` 扣一笔，调用结束再按实际花费
   `settle` 回冲。如果进程崩在两者之间（或被 kill、容器重启），`settle` 不会执行，
   这笔预扣会一直留在账本里，直到 UTC 日切 + 1 小时由 TTL 清掉。ADR-0013 已知这个
   问题，但唯一的观测是 `budget_reserve_leaked` warning 日志——没有「现在有几笔、
   多少钱、最老多久」的数字，排障只能翻日志。
2. **个人「已用/上限」没有拼在一起。** 成本页的「个人日预算」卡片只有配置（默认值与
   覆盖表），要知道某个人今天用了多少、还剩多少，得自己拿 `/admin/cost/summary` 按
   user 聚合。而 `model_calls` 是**结算后的实际成本**，看不到正在执行的预扣，和闸门
   真正使用的账本数字本来就不是一回事。

ADR-0026 的闸门逻辑不需要改；缺的是一条只读路径：**把账本当前状态暴露出来，并和管理页
的配置拼在一张表里**。本次不做自动对账、不做历史趋势、不新增表。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 继续只打 warning 日志 | 现场要回答「谁、多少钱、卡了多久、要不要处理」，日志聚合不是管理页；也没有全局视角 |
| 从 `model_calls` 反推已用与剩余 | 它是结算后的成本，看不到未结算预扣；用它算额度会和闸门的判断不一致（闸门先扣了、成本还没落库） |
| 建审计表 / 定时把账本落库 | 预扣是 Redis 里的短生命周期状态，落库要新增写路径、迁移、清理与一致性校验；报表只读当前状态即可，历史趋势不在本次范围 |
| 用 `SCAN oncall:budget:user:*` 枚举用户 | 这个模式会同时匹配 `...:reservations:*` 与 `...:users:*`，靠字符串约定太脆；SCAN 在大 keyspace 下也不适合每个请求跑 |
| 新增一个独立 key 存预扣时间戳 | 结算必须原子地删两个 key，旧副本只删一个会留下垃圾；时间戳放进同一个 reservations hash 就只多一个字段 |
| **账本只读快照 + 固定 stale 阈值 + 独立 `/usage` + 管理页合并表** | 见下：一份数据一个读取口径，配置、账本、成本三者不混算 |

## 决策

### 1. 两本账各暴露只读 `snapshot()`

```python
BudgetLedger.snapshot() -> LedgerSnapshot
UserBudgetLedger.snapshot() -> dict[str, LedgerSnapshot]

LedgerSnapshot(spent_cents: int, reservations: tuple[ReservationSnapshot, ...])
ReservationSnapshot(token: str, cents: int, age_s: float | None)
```

- 内存与 Redis 两个实现同签名；`spent_cents` 是账本当前值（已含预扣），
  `reservations` 是还没结算的凭证。
- 只读、无副作用；年龄在读取时用 `now - ts` 计算，不落库、不新增列。
- 不把 `limit_cents` 放进 `LedgerSnapshot`：上限是配置（`daily_budget_cents` / 覆盖表），
  账本只回答「扣了多少、还有哪些没结算」。

### 2. 预扣时间戳放进同一个 reservations hash

`_RESERVE_SCRIPT` 在写金额后追加 `<token>:ts`（epoch 秒），`_SETTLE_SCRIPT` 同时
`HDEL` 金额与 ts 字段：

```lua
redis.call('HSET', KEYS[2], token, amount)
redis.call('HSET', KEYS[2], token .. ':ts', now)
...
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1] .. ':ts')
```

- **不新增 key**：结算仍是一次 EVAL，旧副本只删金额也不会让新字段成为独立对象。
- **滚动升级兼容**：旧副本 `reserve` 不写 ts → `age_s = None`，报表显示「—」且**不计
  stale**（宁可少报，不能把老副本的预扣误判成泄漏）；旧副本 `settle` 只删金额 →
  孤立 ts 字段读取时跳过、随 TTL 消失。
- 时间取客户端 `int(time.time())`（`ARGV[5]`），与 reserve 的 TTL、UTC 日切口径一致；
  不用 Redis `TIME`，避免集群/代理下语义不一致，也便于测试。

### 3. 用户枚举用当日集合，不用 SCAN

用户账本新增 `oncall:budget:users:{day}`，在用户账本 reserve 的 Lua 里 `SADD`：

- 全局账本只传 2 个 key，用户账本传 3 个；脚本里 `if KEYS[3] then` 兼容两种调用。
- 集合只增不删当天成员：结算之后用户**仍要**出现在报表里（已花费、无预扣），
  随 TTL 到期消失；不按「当前是否有预扣」过滤。
- 避免 SCAN 与 `oncall:budget:user:*` 的模式误匹配；读取时 `SMEMBERS` + pipeline，
  规模是「当天有模型调用的人」，不是全量用户。

### 4. stale 阈值固定 300 秒

`RESERVATION_STALE_S = 300.0`，是模型请求超时（默认 20s）的 15 倍：一次正常调用从
reserve 到 settle 不应该超过它。

- 不加环境变量：这是「判断异常」的阈值，不是业务配置；可配会让不同副本对同一笔预扣
  给出不同结论。
- `age_s is None`（旧格式）的预扣不计 stale；`oldest_age_s` 只统计有时间的预扣。
- 报表只提示，不自动回冲：补偿需要知道实际花费与幂等键，容易二次记账；日切 TTL 会自愈。

### 5. `/admin/budgets/usage` 只读账本，故障 503 不降级

```http
GET /api/admin/budgets/usage
Authorization: Bearer <admin token>
```

```json
{
  "day": "2026-11-11",
  "stale_after_s": 300.0,
  "global_usage": {
    "limit_cents": 500,
    "spent_cents": 120,
    "reserved_cents": 20,
    "reservation_count": 1,
    "stale_count": 0,
    "stale_cents": 0,
    "oldest_age_s": 2.1
  },
  "users": [
    {
      "user_id": "u_205",
      "spent_cents": 40,
      "reserved_cents": 10,
      "reservation_count": 1,
      "stale_count": 0,
      "stale_cents": 0,
      "oldest_age_s": 2.1
    }
  ]
}
```

- **只读账本**：不读覆盖表、不读 `model_calls`。全局上限取 `settings.daily_budget_cents`；
  个人上限不在这个响应里，那是 `/admin/budgets` 的配置口径，由管理页合并。
- 账本不可用抛 `LedgerUnavailable` → `503 LEDGER_UNAVAILABLE`，**不退回内存账本**：
  Redis 故障时显示「今天没花钱」比报错更危险，管理员会据此加额度或放行。
- 用户按 `user_id` 排序，便于前端稳定合并；`users` 只含有过预扣或花费的人。
- admin only；路由挂在既有 `admin_budgets` 上，不改 `api/router.py`。

### 6. 三个口径互不替代

| 接口 | 回答 | 数据源 |
|---|---|---|
| `GET /admin/budgets` | 每个人**应该**花多少（默认值 + 覆盖） | `user_budgets` / 环境变量 |
| `GET /admin/budgets/usage` | 账本**现在**扣了多少、有几笔没结算 | Redis / 内存账本 |
| `GET /admin/cost/summary` | 已经落库的**实际成本** | `model_calls` |

管理页把 usage 的 `spent_cents` 与 budgets 的 `daily_cents` 拼在同一行，表头标明
「今日已用（账本）」；不把三者相加，也不拿 `model_calls` 去「校正」账本。

### 7. 管理页合并表

- `BudgetLimits` 并行拉 `listBudgets()` 与 `getBudgetUsage()`；纯函数
  `mergeBudgetRows(overrides, defaultCents, usageUsers)` 做 union：
  覆盖表可能包含今天没调用的人，usage 可能包含没有覆盖的人。
- `spent_cents` 在 usage 未加载或失败时为 `null`，显示「—」而不是 0：**未知 ≠ 没花钱**。
- 「剩余」只在「上限 > 0 且已用已知」时计算；上限 0 显示「不限」。
- 全局摘要行显示已用 / 上限 / 未结算笔数 / 超时笔数；`stale_count > 0` 时标红，
  提示检查网关或 Redis。
- usage 失败不影响覆盖表的编辑；配置失败时默认值显示「默认未知」、上限「—」，避免
  把「配置没读到」显示成「默认不限」。

## 后果

- 预扣泄漏从「只有一条 warning」变成可查的笔数、金额与最老年龄；能回答「谁今天花了
  多少、上限多少、还剩多少、有几笔卡住」。
- 账本口径与成本口径的差异被显式展示，不再要求管理员自己对齐 `model_calls`。
- 旧格式（无 ts）的预扣显示「—」年龄、不计 stale，升级窗口内不会误报。
- 用户集合只在个人账本 reserve 时写入：如果某个用户当天只被全局账本扣（个人上限 0
  跳过），他不会出现在 `users` 里——个人报表只关心个人账本，这是正确的。
- 多副本：快照是弱一致读（`pipeline(transaction=False)`），可能读到「金额已扣、ts
  刚写」的中间态；结果是 `age_s=None`，不误报，下一次读取恢复。
- 新增 Redis key `oncall:budget:users:{day}`（TTL 到次日 0 点 +1h）；**不需要迁移**，
  schema 仍到 0013。
- 没有历史趋势、没有自动对账、没有按租户聚合；报表是当前 UTC 日的采样，不是审计账。

## 验证

- `tests/test_budget_usage.py` 新增 8 条（7 pass + 1 条件跳过）：
  - 全局快照：reserve 30+20 → spent 50；settle 7 → spent 27、只剩一笔 20 的预扣；
  - 用户快照按用户分组、rollover 后清空（monkeypatch `_utc_day`）；
  - `summarize`：10@1s、20@301s、5@None → stale 1 笔 20 分，oldest 301.0；
  - 非 admin 403；200 的字段、排序与 `stale_after_s=300`；
  - 账本故障参数化两例（全局 / 用户）→ 503 `LEDGER_UNAVAILABLE`；
  - Redis 快照 roundtrip（设 `ONCALL_TEST_REDIS_URL` 才跑）。
- `tests/test_budgets.py` 的 Redis 清理增加 `_users_key()`，避免测试残留。
- 完整回归：默认 **402 passed + 29 skipped**；`ruff check` 通过、
  `ruff format --check`（164 files）、`mypy app`（103 files）通过。
- 前端：`tsc --noEmit`、`pnpm test` **60 tests / 12 files**、`oxlint` 0/0、
  `oxfmt --check`（65 files）、`pnpm build` 成功。
- 本机没有 Redis：Redis 快照用例按既有条件跳过，未跑真实 Redis；本轮没有 SQL/迁移
  变化，默认套件覆盖内存实现。检索、提示词与多轮判定未改，未重跑评测。

## 待定

- 自动对账/回冲：需要用实际花费与幂等键做补偿，当前只提示、不自动处理。
- 历史趋势（按小时/按天曲线）：现在只有当前 UTC 日快照，长期趋势仍看 `model_calls`。
- 按租户/部门聚合：与 ADR-0026 的租户维度同属一类，等接 IdP 后再做。
- stale 阈值可配：当前固定 300s；如果现场模型超时调大，需要一起评估。
- 预扣明细导出（token、用户、年龄列表）：当前只给聚合统计，排障要逐笔看时再补。
- 旧格式预扣（无 ts）的迁移：现在按「未知年龄」处理，日切自愈；是否需要一次性回填。
