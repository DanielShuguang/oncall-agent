# ADR-0130：工具历史保留清理增加时间索引

## 背景

ADR-0129 给 `tool_setting_changes` 加了独立保留期，清理查询按

```sql
WHERE changed_at < cutoff
ORDER BY changed_at, id
LIMIT batch
```

跨工具裁剪。这个查询无法使用现有 `idx_tool_setting_changes_tool_time`
（`(tool_name, changed_at DESC)`）：它没有 `tool_name` 等值条件，只能全表扫描再排序。
历史表只增，保留清理本身不该随表增长线性变慢。

## 备选方案

| 方案 | 放弃原因 |
|---|---|
| 保持现状，靠表小 | 管理写入虽低频，但清理是周期任务；把性能前提建立在“表不会大”上不可靠 |
| 按工具逐个清理 | 需要先枚举所有工具，且下线工具的历史仍会漏掉；查询次数随工具数增长 |
| 复用 `(tool_name, changed_at DESC)` | 跨工具查询用不上前导列，PG 仍会全表扫描 |
| 删除/重建现有索引为 `(changed_at, id)` | 管理页按工具查最近 N 条的查询会失去可用索引 |

## 决策

1. 在模型与迁移 `0029` 中新增 `idx_tool_setting_changes_time (changed_at, id)`。
2. 保留现有 `idx_tool_setting_changes_tool_time`：一个服务管理页按工具查看，一个服务跨工具保留清理。
3. 迁移只加/删索引，不改表结构；`downgrade` 删除新索引即可。
4. 不在 API 层暴露索引细节；`docs/02` 记录两条索引各自的用途。

## 后果

- 保留清理可走 `(changed_at, id)` 索引做范围扫描 + 有序取批，避免全表排序。
- 多一个索引会增加少量写入成本；`tool_setting_changes` 只在管理写入时追加，可接受。
- 迁移可逆，不涉及数据回填。

## 验证

- 迁移 `0029`：`upgrade head → alembic check → downgrade 0028 → upgrade head` 通过，无漂移。
- 默认 **539 passed + 43 skipped**、PG-only **579 passed + 3 skipped**、PG+Redis **582 passed**；
  `ruff check` / `ruff format --check` 211 files / `mypy app` 119 files 通过。
- 前端未改：36 files / 183 tests。

## 待定

- 用 `EXPLAIN` 在真实数据量上确认规划器选择新索引；当前只验证索引存在与迁移可逆。
- 若未来清理改为按工具分片，再评估是否保留两条索引。


