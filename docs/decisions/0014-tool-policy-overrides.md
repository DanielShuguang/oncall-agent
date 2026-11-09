# ADR-0014 · 工具覆盖存库，工具定义留在代码

- 状态：已采纳（W5 D22/D23）
- 日期：2026-11-09
- 相关：docs/02 §2.5、docs/03 §5、docs/06 §3、docs/10 W5

## 背景

后台要支持「不写代码也能配工具」：启停、角色矩阵。W3 的 `ToolSpec` 是代码里的
不可变值（`roles` / `enabled`），管理页不能直接改进程内存 —— 重启丢失、多副本不一致，
而且权限变更必须能审计。

同时，`input_schema` 不是普通配置：它既约束模型提示词（plan 的 tools 列表），
又是 `validate_args` 的运行时白名单。如果允许管理页在线改 schema，就可能出现
「提示词说 A、校验按 B」的漂移，甚至把保留字段放进 `properties`。

## 选项

| 方案 | 优点 | 代价 |
|---|---|---|
| A. 全量 `tools` / `roles` / `role_tool_permissions` 表，启动时同步代码 | 管理页可编辑一切 | 代码加工具但库没同步会「凭空消失」；schema 双写；每次改动要迁移/同步 |
| B. 只改进程内存，重启回默认 | 实现最短 | 配置不持久、多副本不一致、无法审计 |
| C. 代码持有定义，数据库只存覆盖（**采纳**） | 定义走 code review；覆盖可持久化、可审计；不存在「库缺工具」 | schema 不能在管理页编辑；多副本有最长 2s 生效延迟 |

## 决策

### 1. 职责边界

- 代码（`tools/builtin.py`）：`name` / `description` / `input_schema` / `is_write` /
  `timeout_ms` / 默认 `roles` / 默认 `enabled`
- 数据库（`tool_settings`）：只存与本环境默认值不同的 `enabled` / `roles`
- `NULL` 表示继承：`enabled=NULL` 用代码默认，`roles=NULL` 用代码默认；
  `roles=[]` 表示所有登录用户（与 `ToolSpec.roles=()` 同义）

### 2. 代码禁用是硬边界

生效规则：

```text
enabled = code_enabled AND COALESCE(override.enabled, true)
roles   = override.roles ?? code_roles
```

管理页只能进一步收紧，不能把代码里 `enabled=False`（未就绪/已下线）的工具打开。
接口对这类请求返回 `422 TOOL_LOCKED`，避免「配置绕过发布状态」。

### 3. 覆盖读取

- `ToolPolicy` 在 `ToolGuard` 的存在性检查之后、权限/启用闸门之前应用覆盖，
  所以试调用与真实 run 走同一条路径
- 进程内缓存 2 秒；本进程保存后 `invalidate()` 立即生效，多副本最长 2s
- 读库失败时退回上一份快照（没有则退回代码默认）并打 warning：
  配置面短暂不可用不应让所有工具调用一起 500；硬边界仍由代码 + 闸门兜底。
  管理页走严格读取：读不到真实配置返回 503，不把空/旧快照当成现状，
  避免一次「部分更新」把未提交的工具覆盖整表删掉。

### 4. schema 只读

管理页展示 schema 但不允许编辑。理由：schema 同时面向模型与校验器，在线编辑
需要版本化、回滚、兼容旧 run 的快照，收益远小于风险。新增/修改工具继续走 code review、
`validate_args` 单测与治理测试（docs/06 §2）。

### 5. 角色目录

v1 不建 `roles` 表：角色是 JWT 里的字符串，矩阵页的目录 =
内置 `employee/approver/admin` ∪ `ONCALL_ADMIN_ROLES` ∪ `ONCALL_APPROVER_ROLES`。
自定义角色只要写进配置就能在矩阵里勾选；不在目录里的角色提交时 422。

### 6. 审计

`tool_settings.updated_by` 记录最后修改人，`updated_at` 记录时间；完整变更历史
由结构化日志 `tool_setting_updated` / `perm_matrix_updated` 提供。v1 不建独立的
配置审计表（与审批审计不同，配置错误可通过重放/日志追溯）。

## 后果

- 新增 `tool_settings` 表（迁移 0007）、`tools/policy.py`、`api/admin_tools.py`；
  `ToolGuard` 增加可选 `policy` 参数，默认无覆盖时行为不变
- 试调用只能验证「会挂起审批」，不能真的执行写工具；需要真实工单时仍走对话 + 审批
- 权限矩阵保存是「按工具部分更新」：未提交的工具保持原样，避免一次误操作清空全部配置
- 多副本部署若要求秒级一致，需要把 TTL 改成 pub/sub 失效或每次读库；
  当前按「单实例 + 可接受 2s」取舍

## 待定

- 是否需要配置变更历史表（谁在何时把哪个工具从哪些角色改成哪些角色）
- 自定义角色是否需要独立的 roles 表与组织架构同步
- 管理页是否提供「只读 schema diff」用于 review 新工具
