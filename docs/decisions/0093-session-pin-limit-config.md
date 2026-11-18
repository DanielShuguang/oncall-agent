# ADR-0093：置顶上限可配置

- 状态：已采纳（W6 后补）
- 日期：2026-11-18
- 相关：[ADR-0069](0069-session-pin.md)、[ADR-0073](0073-session-pin-limit.md)、
  [ADR-0074](0074-session-pin-capacity.md)

## 背景

ADR-0073 把单用户置顶上限固定为 50，并在 ADR-0074 里把 `pinned_count` /
`pin_limit` 透出给前端做提前禁用。50 是按「侧栏首屏不被打爆」估的经验值，
但不同部署的用户规模、会话量和合规要求并不一样：

- 小型私有化部署可能希望更小（例如 20），让首屏更干净；
- 会话很多、以置顶做「工作台」的团队可能希望更大（例如 80）；
- 固定值让运维只能改代码或让用户忍着，README 的已知局限里也明确写了
  「不提供环境变量」。

ADR-0073 的「待定」已经记了「上限是否改为环境变量/租户策略」，本 ADR 先把
**部署级环境变量**做掉，不引入租户/用户级策略。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 保持固定 50 | 否决 | 不同部署的列表规模差异真实存在，改代码才能调不合理 |
| 环境变量 `ONCALL_SESSION_PIN_LIMIT` | **采纳** | 与现有 `ONCALL_*` 配置一致，无迁移，改后重启生效 |
| 存 `settings` 表、管理页热改 | 否决 | 多一次读库与缓存失效；置顶上限是部署参数，不是高频运营开关 |
| 按用户/租户单独配置 | 否决 | 当前身份模型没有租户目录；按用户配置会把列表契约变成 N 套 |
| 不设上限，只在 UI 提示 | 否决 | 提示不阻止数据增长，置顶段仍会压垮首屏 |
| 达到上限自动淘汰最久未活动 | 否决 | 静默改变用户偏好 |

## 决策

1. **默认值仍是 50**：`Settings.session_pin_limit` 默认 50，与 ADR-0073 的历史
   行为一致；部署可用 `ONCALL_SESSION_PIN_LIMIT` 覆盖。启动期校验 `< 1` 直接
   拒绝，错误信息为 `ONCALL_SESSION_PIN_LIMIT 必须 >= 1`。
2. **配置在构建 store 时注入**：`build_store(settings)` 把
   `settings.session_pin_limit` 传给 `InMemoryRunStore` 与 `PostgresRunStore`；
   两者都暴露 `pin_limit` 属性。内存/PG 的置顶检查都读 `self.pin_limit`，
   不再直接引用模块常量。
3. **列表返回实际值**：`GET /sessions` 的 `pin_limit` 改为 `store.pin_limit`，
   409 的 `PinLimitExceeded` 也带上实际值；前端继续以响应为准，不写死 50。
4. **改配置重启生效**：不做热加载/多副本广播；同一部署的所有副本应使用同一
   环境变量。若副本配置不一致，列表/409 会按各自进程的值返回，这是部署错误，
   不在本 ADR 的自动收敛范围。
5. **既有超限数据不回溯**：上限调小后，已经超过新上限的用户仍可查看/取消置顶，
   但新增置顶会被拒；不自动删除置顶行，避免静默改变用户偏好。
6. **不新增迁移/接口**：上限是进程配置，不落库；不新增容量查询接口，
   `pinned_count`/`pin_limit` 仍随列表返回。
7. **并发语义不变**：PG 仍用 `pg_advisory_xact_lock(hashtext(user_id))` 串行化
   同一用户的置顶检查与插入；内存实现仍在 store 锁内完成。上限值只影响阈值。

## 后果

- 部署可以按用户规模调整置顶上限，不用改代码；默认行为与 ADR-0073 完全一致。
- `pin_limit` 从「契约常量」变成「部署相关值」，文档与前端都必须把它当响应字段；
  多副本配置不一致时会出现不一致的 409/列表提示，属于运维配置问题。
- 上限调小不会清理既有置顶；用户需要自己取消到新上限以下才能继续新增。
- 没有按租户/用户的差异化上限；需要时再单开 ADR，届时要考虑身份模型与列表契约。

## 验证

- `server/tests/test_config.py`：`session_pin_limit=0` 被拒绝；`80` 能正常解析；
  `build_store` 把 `session_pin_limit=7` 注入内存 store，断言 `store.pin_limit == 7`。
- `server/tests/test_sessions_api.py::test_pin_session_limit`：把 store 上限设为 1，
  第一个置顶 204、列表返回 `pin_limit: 1`、第二个置顶 409，错误文案带实际
  `1 个` 上限。
- `server/tests/test_store_contract.py`：内存与 PG 契约中临时把 `store.pin_limit`
  设为 1/2，验证超限异常与并发恰好 2 个成功；finally 恢复原值。
- 实测：默认 **519 passed + 40 skipped**、PG-only **556 passed + 3 skipped**、
  PG+Redis **559 passed**；`ruff check` / `ruff format --check` 200 files、
  `mypy app` 116 files 通过。
- 前端未改代码；沿用 26 files / 128 tests、`tsc --noEmit`、oxlint 0/0、
  oxfmt 135 files、`pnpm build` 通过。
- 本次无新迁移，未执行迁移往返；`0022` 保持不变。

## 待定

- 按租户/用户差异化上限（需要先有租户目录或用户配置表）。
- 上限变更后的管理页提示/审计（谁在何时改了部署配置）。
- 置顶容量是否增加独立查询接口（当前随列表返回已够用）。
