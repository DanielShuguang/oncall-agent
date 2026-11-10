# 0022 · 回答内容的按当前可见性回收：引用快照 + 读时校验

- 状态：已采纳（W6 后补）
- 日期：2026-11-10
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/07-frontend-design.md](../07-frontend-design.md)、[ADR-0019](0019-document-level-access.md)、[ADR-0020](0020-multi-turn-context.md)、[ADR-0021](0021-data-retention.md)

## 背景

ADR-0019 把文档级可见性做进了**检索、引用预览与管理接口**，但已经产生的 run 不会跟着重算：

- `runs.output` 是回答正文的副本，里面可能整句引用受限文档；
- `message.completed.citations[].snippet` 在事件里同样是原文片段；
- ADR-0020 的多轮历史把上一轮回答喂给模型，模型会把同一段正文复述进新回答；
- 撤销角色 = 重新签发一个没有该角色的 token；旧 run 的回放却仍按"当时能看"展示。

结果就是：文档收权后，用户在 `/runs/:id`、事件补拉、幂等重放与下一轮追问里，仍能读到
已经不该看的内容。ADR-0019 上线时就记下了这条已知边界，ADR-0021 的「待定」里也有一条
「角色撤销后如何回收历史内容」。这次把它做掉。

两条已有约束让"最简单的做法"不可行：

1. **事件不是永久的**：`run_events` 默认 180 天后按 run 整场清理（ADR-0021），
   只在事件里找引用的话，清理过的 run 就永远无法重算。
2. **可见范围随时可变**：管理员可以 `PATCH /admin/kb/documents/{id}/access` 改窄/改宽，
   也可能删除或重传文档；内容回收必须按"读的那一刻"判定，而不是生成时快照。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 生成回答时快照可见性，之后不再校验 | 角色与文档范围都会变；快照在变更那一刻就错了，改宽也要重算 |
| 可见范围变更时回扫所有 run、改写或删除 `output` 与事件 | 破坏 R1/R2 与回放一致性；一次 `PATCH` 变成跨表大事务；改回可见时无法恢复；多副本还要做分布式任务 |
| 不存快照，读时从事件现取 `citations` | 事件被清理后引用就没了，正好落在最需要回收的旧 run 上（ADR-0021 已确认会删 180 天前的事件） |
| 撤权时删除 run / 全部事件 | 运行列表、成本口径、失败归因与审批证据一起丢；撤权不是"删账" |
| **引用快照落 `runs` + 读时按当前可见性校验 + 失败关闭** | 变更立即生效、可逆（范围改回来自动恢复）、不改写历史；代价是一列加一次查询 |

## 决策

### 1. 引用快照落在 `runs.cited_document_ids`

- `message.completed` 投影时，从 `citations[].document_id` 抽出去重保序的 id 列表
  （上限 50），与 `output` 在**同一事务**里写进 `runs`（迁移 0011，JSONB 默认 `[]`）。
- 必须落在 `runs` 而不是只读事件：事件 180 天后会被整场清理，`runs.output` 却继续保留；
  引用快照跟着事件消失，清理过的 run 就再也不能回收。
- 不是新事件（R1）：它是 `runs` 的汇总投影，和 `output` / `token_in` 同级；事件契约不变。
- 空数组的含义是「这轮明确没有引用」（工具类回答、拒答）；`citations` 不是数组时不改字段，
  避免旧 payload 把已有快照清空。存储层契约测试覆盖去重、非字符串/空 id、缺字段与空数组。

### 2. 读时按当前可见性校验，fail-closed

- 判定的单位是**整场 run**：引用的文档全部当前可见才展示；任何一篇不可见 → 整场内容不展示。
  一段回答无法按文档切开，展示"半段"只会让用户以为剩下的引用不存在。
- 查不到的文档按不可见处理：删除也是一种收权，管理员删掉一篇文档后，旧回答里由它生成的
  正文同样不该继续展示。这是 `fail-closed` 的直接代价（见「后果」）。
- `admin`（`ONCALL_ADMIN_ROLES`，知识库所有者）不受限，与 ADR-0019 一致：本来就能改内容，
  对管理员隐藏正文只是形式主义，也会让管理页自相矛盾。
- 没有引用（`[]`）直接放行，不查知识库：大部分工具类回答与拒答不付这次查询。

### 3. 覆盖四条读取路径

| 路径 | 行为 |
|---|---|
| `GET /runs/{id}` | `content_redacted=true`、`output=null`；`input`、状态、计量、失败归因照常 |
| `GET /runs/{id}/events` | `200` + `events: []` + `content_redacted=true`（run 还在，回放不可用） |
| `POST /chat/stream` 幂等重放 | `403 CONTENT_REDACTED`：不能靠重试 `client_msg_id` 把旧回答再流一遍 |
| `recent_turns()` 多轮历史 | 剔除引用了不可见文档的轮次；跨轮合并成一次批量查询 |

- `input` 不回收：那是用户自己敲进来的问题，不是知识库正文；回收它会让运行列表变成空白，
  也解决不了"回答里引用了受限正文"。
- 事件**整场**不回放，而不是只过滤 `message.completed`：时间线缺了回答更难解释，而
  `message.delta` / `step.completed` 的摘要同样带正文片段。
- 历史过滤只丢整轮、不裁剪正文：半句旧回答喂给模型比没有历史更糟；否则模型会在新回答里
  复述旧内容，读接口的回收就白做了。

### 4. 批量校验与召回共用同一条 SQL 条件

- `KnowledgeStore.visible_document_ids(ids, viewer)`：Postgres 复用 `_visibility_clause`
  （与稀疏/稠密召回、引用预览同一条规则），内存实现用 `is_visible`；不存在的 id 不在结果里。
- `tests/test_rag_acl.py` 与 `tests/test_rag_pg.py` 用同一张 (visibility × 角色) 矩阵断言
  批量结果与 `is_visible` 一致，规则改动会同时打红两边。
- 每场 run 一次查询；多轮历史把 3 轮的 id 合并成一次查询；事件补拉只在终态 run 上取
  引用快照、有引用时才查知识库（运行中的 run 还没有引用），不给每秒轮询的路径加固定开销。

### 5. 兼容与回填

- 迁移 0011 用 `jsonb_path_query` 从存量 `message.completed` 事件回填；lax 模式对
  缺失/非数组路径返回空集，脏 payload 不会让升级失败。
- 回填不到的 run（事件已清理）保持 `[]`，回答不会因权限变更被隐藏——这是本次之前的
  存量局限，写在「代价」里；要覆盖它只能先做事件冷归档（ADR-0021 待定）。

## 后果

**收益**

- 撤权立即生效：不需要后台任务、不需要重扫历史、不改写事件；可见范围改回去，旧回答自动恢复。
- 回收判定只有一处（`app/runs/content.py`），四条读路径共用，不会出现"详情页藏了、
  事件接口还漏着"。
- 引用快照与事件生命周期解耦：事件清理后仍能按当前可见性回收，与 ADR-0021 互补。
- 展示口径可解释：能看到的回答都满足"当时引用的文档，现在仍可见"。

**代价与已知风险**

- **重传会误伤**：`delete_by_source` + 新 UUID 意味着重新上传会换 `document_id`，旧引用
  因此按不可见处理。正常维护一次知识库就可能隐藏一批旧回答；要消除它需要"文档身份"
  （source+checksum 或软删除归档），不在本次范围。
- 文档改名（`source` 变）同理；回填失败的存量 run（事件已清理）不回收。
- 只覆盖知识库引用：CMDB/工单工具结果、用户输入、审批载荷不在回收范围。审批快照
  （`approvals.state`）目前不返回给前端，但里面确实保留了当时的检索上下文，后续做
  审批侧回收时要一起看。
- 读详情/回放会多一次 `kb_documents` 查询（有引用时）；没有做延迟基准。批量查询按主键
  `= ANY`，规模是单场 run 的引用数（≤50）。
- 角色是 JWT 里的标签（没有 roles 表）：撤权靠重新签发 token，旧 token 在有效期内仍按
  旧角色判定（`ONCALL_TOKEN_TTL` 内），这是本地 JWT 的既有边界（ADR-0010）。
- 事件已清理且引用快照为空的历史 run（迁移前数据）不会回收。

**待定**

- run 内容的**按时间**保留（`runs.input/output` 的 TTL）：与权限正交，ADR-0021 的待定项
  只完成了"撤销角色后回收内容"这一半
- 文档身份（source+checksum / 软删除归档）以消除重传导致的回收误伤
- 审批快照（`approvals.state`）里的检索上下文如何处理
- 读路径多一次查询的延迟基准

## 验证

- `tests/test_store_contract.py` 新增 `_exercise_cited_documents`：内存与 Postgres 共用
  （投影去重保序、非字符串/空 id 忽略、缺字段不改、空数组清空、`recent_turns` 带快照、
  未知 run 返回 None）。
- `tests/test_runs_content.py` 6 条：无引用直接放行、admin 放行、任一不可见整体回收、
  重复 id 按集合比较、查不到按不可见、历史过滤只丢整轮且保持顺序。
- `tests/test_runs_api.py` 7 条：可见时正常、收权后详情 `output=null` 且事件 200 + 空、
  恢复可见后自动恢复、admin 与匹配角色可见、文档不存在也回收、事件清理与回收同时成立。
- `tests/test_chat_stream.py` 2 条：上一轮引用被收权后追问回到拒答；幂等重放返回
  `403 CONTENT_REDACTED`。
- `tests/test_rag_acl.py` / `tests/test_rag_pg.py`：批量可见性与 `is_visible` 矩阵一致
  （内存 + SQL）。
- 迁移 0011 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；开发库回填 307/310
  场 run（其余 3 场没有 `message.completed` 事件）。
- 默认 **315 passed + 24 skipped**；带 Postgres **339 passed**（2026-11-10 本机 WSL2 + Docker 复跑）。
- 前端 `RunDetailPage` 用 `content_redacted` 显示提示并隐藏回答与回放；`tsc --noEmit`、
  `vitest 55/55`、`oxlint 0`、`oxfmt --check` 通过，`pnpm build` 成功。
