# 0019 · 文档级可见性：在召回之前过滤

- 状态：已采纳（W6 后加固）
- 日期：2026-11-09
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/05-rag-design.md](../05-rag-design.md)、[ADR-0018](0018-citation-fulltext-preview.md)

## 背景

D24 把引用从「只能看片段」补成「可以跳全文」之后，知识库对任何登录员工都是可读的
（[ADR-0018](0018-citation-fulltext-preview.md)）。当时的边界是「与检索同一可见性」，
并在决策里留了一句约束：**将来做文档级 ACL，必须先在检索侧过滤**。

这个约束现在必须兑现。企业知识库不可能全部公开：

- 薪酬、年终奖、调薪窗口这类 HR 文档，普通员工不该检索到，更不该点开；
- 合同模板、财务口径、安全事件复盘，通常只给特定团队；
- 一旦这些文档进了公共检索池，泄漏路径不止一条：召回的切片 → 引用片段 →
  引用跳全文 → 管理页切片预览。只堵其中一个出口没有意义。

同时还有两个现实约束（这也是 v1 不做复杂权限模型的原因）：

1. 没有 `roles` 表。角色是 JWT 里的字符串标签，由部署方用
   `python -m app.cli token --roles employee,hr` 签发，权限矩阵页的「角色目录」
   （`app/core/roles.py`）只是内置角色 + 管理/审批角色配置的并集，**不是**白名单。
2. 文档之间是平铺的，没有目录树、部门树、继承关系。要的是「这篇只给 hr 看」，
   不是一套 ABAC 策略语言。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 先照常检索，返回前把不可见的过滤掉 | 受限文档会占掉 `candidates=20` 的名额，把可见文档挤出 top_k（用户看到「命中 2 条」而不是 3 条）；RRF/文档级加分的排序也被不可见内容污染；命中数变化本身就是存在性侧信道 |
| 只在预览接口判权，检索不管 | 泄漏面最大的其实是引用片段：`message.completed.citations` 里就有正文，等于 ACL 形同虚设 |
| 每人一个知识库分区 | 绝大多数文档是共享的，为少数受限文档复制整库，存储与更新成本都不划算 |
| 引独立策略引擎（OPA/Casbin）或规则 DSL | 私有化现场多一个组件、多一份策略文件；v1 只需要「公开 / 指定角色」两档，收益不成立。将来出现「按部门 + 密级 + 时间」的组合需求时再评估 |
| 给每篇文档单独一份「允许用户」白名单 | 人变动就要改库；角色标签随 token 走，天然跟着组织变化收敛，且与工具权限矩阵用同一套身份来源（R9） |

## 决策

**一条规则，两个实现，一份数据。**

### 1. 数据

`kb_documents` 增加两列：

```sql
visibility    VARCHAR(16) NOT NULL DEFAULT 'public',   -- public | roles
allowed_roles VARCHAR(32)[] NOT NULL DEFAULT '{}',
CHECK ((visibility = 'public' AND cardinality(allowed_roles) = 0)
    OR (visibility = 'roles'  AND cardinality(allowed_roles) > 0))
```

- 两种解释必须互斥：`public` 不许带角色，`roles` 至少一个角色。没有这条 CHECK，
  「public 但有角色」在 SQL 过滤和 Python 判定里会有两种读法。
- 存量文档由 `server_default='public'` 落成公开：**升级行为是「可见性不变」**，
  不是把旧文档默认锁死。需要收紧就逐篇 `PATCH`。
- 角色列用 `varchar(32)[]` + `&&`（数组重叠）过滤，不建关联表：v1 一篇文档最多
  20 个角色，查询就是一次重叠判断。

### 2. 规则（`app/rag/access.py`）

```
可见 ⇔ viewer.unrestricted
       ∨ visibility = 'public'
       ∨ viewer.roles ∩ allowed_roles ≠ ∅
```

`viewer.unrestricted` 来自部署侧的 `ONCALL_ADMIN_ROLES`：`admin` 是**知识库所有者**。

为什么管理员不受限：它本来就能上传、覆盖、删除、重建索引；对所有者隐藏正文只是
形式主义，还会让管理页的切片预览自相矛盾（列表里看得见，点开却是 403）。
注意这不是层级结构：`admin` 读全库，`hr` 只读 HR 文档，没有「谁继承谁」。

### 3. 两个实现，用矩阵用例锁住等价性

- 召回：`PgKnowledgeStore.sparse_search/dense_search` 在 `JOIN kb_documents` 后
  把可见性条件写进 `WHERE`，**在 `LIMIT` 之前过滤**。
- 单篇读取（引用全文 / 管理详情）：`is_visible()` 纯函数。
- 内存实现（测试、无库 demo、seed）走 `is_visible()`。

两种实现不可能合并成一份代码，所以用测试保证同一条规则：`tests/test_rag_acl.py`
扫 (可见性 × 角色) 矩阵断言内存实现与规则一致，`tests/test_rag_pg.py` 用同一张
矩阵逐条比对 SQL 过滤结果与 `is_visible()`。改规则时先改 `access.py`，再跑这两组。

### 4. 接口行为

- 上传：`POST /admin/kb/documents` 增加 multipart 字段 `visibility`（默认 `public`）
  与 `allowed_roles`（逗号分隔）。校验失败返回 `422 INVALID_ARGS`。
- 改范围：`PATCH /admin/kb/documents/{id}/access`（整体替换，`visibility` 与
  `allowed_roles` 两项必填，避免空 body 被解释成默认值）。**不重新切分**，`chunk_id` 不变，
  已有引用继续可点；如果为了改权限而重传文件，`document_id` 会变，历史引用全部失效。
- 列表 / 详情 / 预览响应都带 `visibility` + `allowed_roles`；映射只在
  `KbDocumentOut.from_document` 一处，避免「列表显示公开、实际是 roles」。
- 引用全文：不可见与不存在**都返回 404**。403 等于承认「这篇文档存在，只是你不能看」，
  而 `document_id` 本来就是不可猜的 UUID；用 404 让两种情况和外部行为一致。

### 5. 演示语料与评测

seed 的 50 篇里把一篇噪声文档换成 `hr` 受限的「薪酬、年终奖与工资条查询（HR 专用）」，
总数不变，评测用例引用的文档一个没动。这带来一个附带的金丝雀：
评测的 `neg-bonus`（「公司年终奖什么时候发」必须拒答）现在**同时**验证 ACL ——
语料里明明有这篇，员工身份仍然检索不到。如果哪天 ACL 在内存实现上失效，
50/50 会立刻掉下来。

## 后果

- 泄漏面收敛到「公开文档 + 本人角色能看的文档」。引用片段、跳全文、管理页详情
  共用同一判定，不存在「预览能看、检索不给」或反过来的缝隙。
- 召回 SQL 多一次 `kb_documents` join。**`LIMIT` 拿到的仍是「可见的前 N 条」**：
  这是 SQL 语义（`WHERE` 先于 `LIMIT`），与执行计划无关，受限文档不会占候选名额
  （`test_rag_pg.py` 的 limit 用例守住这一点）。但**物理计划没有验证**：数据量小时
  planner 会走全表扫描 + 排序，万级 chunk 下 HNSW 是否仍被选中、join 过滤的代价多大，
  既没有 EXPLAIN 记录也没有延迟对比基准。真上量时先看执行计划，再决定
  `(visibility, allowed_roles)` 索引或物化视图——不要拿这段文字当性能结论。
- 角色名不做白名单校验（没有 roles 表），只校验语法。拼错角色名不会报错，
  而是让这篇文档除管理员外谁都看不到——控制台列表里能看到实际角色，用
  `PATCH` 改回来即可；这条写进了 docs/03 与前端提示。
- 仍然**没有**：按用户授权、部门树继承、文档密级、临时授权/过期、按切片的细粒度
  权限。要做这些，扩展点是 `access.py` 的规则 + 两个实现的过滤条件；数据上需要
  grants 表，且**必须先改检索侧**（ADR-0018 的约束继续有效）。
- 管理页仍是「管理员可读全部正文」。如果客户的合规要求是「管理员也不能看内容」，
  这个模型不适用，需要在部署层拆成两个角色（内容管理员 / 系统管理员），v1 不做。
