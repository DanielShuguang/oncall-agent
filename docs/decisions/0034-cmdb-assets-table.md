# ADR-0034：`query_cmdb` 查 `assets` 表并注入身份

- 状态：已采纳
- 日期：2026-11-12

## 背景

`query_cmdb` 从 W1 起就用进程内常量 `FAKE_ASSETS`，只认识 `u_102` / `u_205` 各一台设备。
但另外两件事早已发生：

- 迁移 `0003` 的注释写着「W3 让工具真正查表」，`docs/06` §8.3 也一直标注
  「`query_cmdb` 仍是进程内假数据」；
- W2 的 seed 已经把 200 条资产写进 `assets` 表，`tickets.asset_id` 还外键引用它。

也就是说，演示数据在库里，工具却还在读常量：seed 的资产对 Agent 不可见，用户换一台设备
就查不到。更麻烦的是身份：旧实现让模型/规则把 `owner_id` 放进 args，接真实数据后
这等于把「查谁」交给模型（R9 的隐患），而不是由服务端身份决定。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 继续用 `FAKE_ASSETS` | 与 seed、迁移注释、文档长期不一致；真实数据进不来 |
| 直接 HTTP 调真实 CMDB | 本仓库没有可依赖的 CMDB 服务；私有化交付不应假设外部地址与凭据 |
| 新建一张资产表 | `assets` 表、seed、外键都已存在，重复建模没有收益 |
| **采纳：新增资产仓储，读 `assets` 表；身份由 ToolGuard 注入** | 复用既有表与 seed；内存/PG 两实现；换真实 CMDB 只替换 repository |

## 决策

1. **新增 `app/tools/assets.py`**：`AssetRepository` 协议只有
   `list_for_owner(owner_id, *, asset_id=None, limit=20)`。内存实现带一份最小
   `DEMO_ASSETS`（无库演示/测试），Postgres 实现查 `assets` 表；`build_asset_repository`
   按 `store_backend` 选择，单例与 `tickets` 仓储同构。
2. **身份只来自服务端**：`query_cmdb` 的 `input_schema` 只剩可选 `asset_id`，
   `owner_id` 从 schema 移除，`ToolSpec.inject_identity=True` 由 `ToolGuard` 注入
   `identity.user_id`；模型传 `owner_id`/`user_id` 会在 `validate_args` 处被拒（R9）。
   `plan` 的规则分支不再写 `args={"owner_id": ...}`，`_calls_from_text` 也不再补身份字段，
   `prompts/plan.md` 的示例同步改为 `args: {}`。
3. **空结果是合法结果**：查不到资产返回 `{"assets": [], "count": 0}`，不是
   `not_found` 错误；`finalize` 用「你名下暂时没有查到资产记录」解释，再给通用建议。
4. **查询语义**：只返回 `owner_id = 当前用户` 的资产；可选 `asset_id` 精确缩小，
   仍然叠加 owner 过滤，不能越权；按 `asset_id` 升序、最多 20 台。
5. **`finalize` 支持多台**：1 台沿用「已确认你名下的 {型号}（{编号}）状态为 {状态}」；
   2–3 台列全；超过 3 台说「已确认你名下 N 台资产，例如：」并列前 3 台。
   工具失败仍走原降级话术「资产信息暂时没查到（数据可能过期）」。
6. **无迁移**：`assets` 表早已存在，本轮没有加列/加索引；`owner_id` 暂不建索引，
   200 条 seed 数据下顺序扫描可接受，接真实 CMDB/更大数据量时需要补（写进待定）。
7. **真实 CMDB 的替换点只有一个**：实现一个 `AssetRepository`，把
   `build_asset_repository` 指过去即可；工具 schema、超时、角色约束与治理链路不变（R3）。

## 后果

- Agent 现在能查到 seed 里的全部 200 条资产，不再只认识两台演示设备；
  `u_102` 名下有两台（笔记本 + 显示器），资产类回答会从单台变成「2 台资产」。
- `query_cmdb` 的调用参数从 `{"owner_id": ...}` 变成 `{}`，但响应从单个资产 dict
  变成 `{"assets": [...], "count": N}`；前端工具卡直接展示 JSON，不需要改。
- 模型再也不能指定查谁的资产；伪造 `owner_id` 会被 schema 判非法并触发重试/规则兜底。
- 无库演示仍可跑：`ONCALL_STORE_BACKEND=memory` 时用 `DEMO_ASSETS`，不依赖 seed。
- 空资产不再算工具失败，`verify` 不会因此重规划；这是「合法空结果」与「工具故障」的分离。

## 验证

- 默认 `uv run pytest`：**433 passed + 32 skipped**。
- 真实 Postgres（pgserver 临时实例）：**462 passed + 3 skipped**。
- 再加 `ONCALL_TEST_REDIS_URL`（WSL Redis 6390）：**465 passed**（45.12s）。
- 新增/修改：`tests/test_assets.py` 3 条（只查本人、`asset_id`/limit、注入资产）、
  `tests/test_assets_pg.py` 1 条（真实 PG 读表、owner 隔离、保修日期）；
  `test_agent_runtime.py` 改为断言 `args == {}`、结果 `count == 2`；
  `test_agent_llm.py` 改为断言伪造 `owner_id` 被拒后规则兜底；
  `test_admin_tools.py` 试调用/权限矩阵改传 `{}` 并注入 admin 资产；
  `test_agent_graph.py` 增加多台/空/失败三路 finalize 断言。
- `ruff check` / `ruff format --check`（174 files）/ `mypy app`（105 files）通过。
- 前端未改：`tsc`、**64 tests / 13 files**、`oxlint` 0/0、`oxfmt --check` 69 files。
- 没有 SQL 迁移；检索、提示词、多轮判定未改，未重跑 RAG 与多轮评测。

## 待定

- `assets.owner_id` 索引：当前 200 条无压力；接真实 CMDB 或数据量上来后需要补。
- 资产分页/搜索：现在最多返回 20 台、按资产号排序；多设备用户没有翻页与按类型筛选。
- `type` / `status` 枚举与中文映射：仍按库里的字符串直出，前端/回答没有统一词表。
- CMDB 同步：本地 `assets` 表目前由 seed 写入；真实环境的增量同步、负责人变更未设计。
- 资产级权限：现在只按 owner；共享设备、离职转移、IT 代查需要新的权限模型。
