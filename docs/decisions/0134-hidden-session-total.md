# ADR-0134：已移除会话列表首屏总数

## 背景

`GET /sessions/hidden` 支持 keyset 分页与标题搜索（ADR-0047），但响应只有
`items` 和 `next_cursor`。用户打开「已移除」折叠区时只能看到「已加载 N 条」，
不知道过滤后还有多少条；审批列表、恢复审计、置顶审计都已采用「第一页附
`total`、后续页为 `null`」的口径（ADR-0057/0064/0088）。

## 备选方案

| 方案 | 不采纳原因 |
|---|---|
| 前端一直显示「已加载 N 条」 | 无法判断是否还有下一页之外的记录 |
| 让列表接口返回全部记录再前端分页 | 破坏 keyset 分页，深页/大表不可接受 |
| 每次翻页都算总数 | 后续页用不到 total，白付一次 count 查询 |
| 第一页附 `total`，后续页 `null` | 采纳：与现有管理列表一致，成本只落在首屏 |

## 决策

1. `RunStore` 增加 `count_hidden_sessions(*, user_id, query=None)`，过滤与
   `list_hidden_sessions` 同口径：只统计有 run 的移除行，`query` 同时匹配
   自定义标题与首条非空问题。
2. `GET /sessions/hidden` 只在 `cursor` 为空时调用计数；有游标时 `total=None`。
3. 计数与列表是两次查询，不是同一快照。若计数后会话被恢复，出现
   `total < len(items)`，把 `total` 降级为 `null`（与 ADR-0057/0064/0088 一致），
   不让前端显示「共 0 条 · 已加载 1 条」。
4. 计数失败与列表失败同一处理：记日志并返回 503 `DATABASE_UNAVAILABLE`，
   不返回部分列表。
5. 前端折叠区在已有记录时显示「共 N 条 · 已加载 M 条」；`total=null` 时只显示
   「已加载 M 条」。恢复单条后本地把已知 total 减一，批量恢复后重拉第一页。
6. 无迁移；`hidden_sessions` 现有索引与查询不变。

## 后果

- 首屏多一次 `count(distinct session_id)`；数据量是单用户已移除会话，且只在
  打开折叠区/切换搜索时发生。
- `total` 是首屏时刻的近似值；并发恢复可能让它偏大，下一轮筛选/展开会纠正。
- 搜索时 total 按当前 `q` 统计，不是全量已移除数。

## 验证

- store contract（内存 + PG）：隐藏 1 条后 count=1、搜索命中 1、无关搜索 0；
  隐藏 3 条后 count=3、`vpn` 命中 1、其他用户 0。
- API：首屏 `total=1`；恢复后空列表 `total=0`；`limit=1` 首屏 total=2 且有
  cursor，下一页 `total=null`；计数抛 `SQLAlchemyError` 返回 503。
- 默认 540 passed + 43 skipped；PG-only 580 passed + 3 skipped；PG+Redis 583 passed。
- ruff 211 / format 211 / mypy 119；前端 38 files/191 tests、lint 159、format 167、
  build 2956。

## 待定

- 已移除列表的排序字段/自定义排序；
- 首屏 total 的缓存（当前每次展开重算）。
