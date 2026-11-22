# ADR-0108：恢复已移除会话时恢复置顶

- 状态：已接受
- 日期：2026-11-22
- 相关：[ADR-0069](0069-session-pin.md)、[ADR-0072](0072-session-batch-hide.md)、[ADR-0100](0100-tool-history-pagination.md)

## 背景

ADR-0069 规定「从侧栏移除」与置顶互斥：移除会话时同一事务清掉 `pinned_sessions`，
恢复时只删 `hidden_sessions`，不会恢复置顶。ADR-0072 的批量移除沿用了这个行为。

实际使用中，用户把常用会话从列表移除，通常是为了临时腾出位置，而不是放弃置顶。
恢复后还要重新找到会话、重新点击置顶，对常驻会话是重复劳动。隐藏行目前也没有记录
「移除时是否置顶」，恢复端无从判断。

## 备选方案

1. **保持不恢复**：实现最简单，但用户每次恢复后都要手动重新置顶；README 已把它列为
   已知局限。
2. **恢复时一律置顶**：会让恢复绕过置顶上限，可能把用户已有的置顶挤掉，也破坏
   `PIN_LIMIT_REACHED` 的容量语义。
3. **恢复时按容量尽力置顶**（采纳）：隐藏时记录 `was_pinned`，恢复时在容量允许范围内
   按请求顺序恢复；容量不足的会话仍然恢复，只是保持未置顶。
4. **单独建置顶快照表**：能表达更多状态（置顶时间、来源），但多一张表和一套生命周期，
   当前只需要一个布尔值，不划算。

## 决策

1. `hidden_sessions` 增加 `was_pinned BOOLEAN NOT NULL DEFAULT false`（迁移 `0027`）。
   旧行默认 `false`，升级后首次恢复不会自动置顶；不回填历史。
2. 隐藏时先读取该用户 `pinned_sessions` 中属于这批会话的 id，再插入隐藏行（重复移除
   保留首次值），最后删除置顶行；读写在同一事务内完成。
3. 恢复时先取用户级 advisory lock（与置顶/隐藏共用），保证容量检查与插入串行：
   - `DELETE FROM hidden_sessions ... RETURNING session_id, was_pinned`；
   - 对真正恢复的会话清掉可能残留的置顶行；
   - 计算 `available = pin_limit - 当前置顶数`，按请求顺序取 `was_pinned` 的前
     `available` 个插入 `pinned_sessions`（`ON CONFLICT DO NOTHING`）。
4. 容量不足不是恢复失败：会话照常恢复，只是不置顶；已有置顶不会被挤掉。
5. 恢复触发的置顶**不写** `session_pin_audits`。审计只记录用户主动 pin/unpin，
   避免把系统补回的动作伪装成用户操作；恢复本身由 `session_restore_audits` 记录。
6. 内存实现用 `_hidden_session_pins` 保存同样的布尔状态，与 PG 同口径；批量恢复按
   API 请求顺序恢复，去重由现有入口完成。
7. 不做置顶时间恢复、不做跨用户恢复、不做批量置顶；不新增索引。

## 后果

- 用户恢复常用会话时，置顶会自动回来；容量满时恢复仍成功，只是需要手动腾位置。
- 隐藏/恢复多了一次置顶读写，但都在现有事务/锁内，没有新增往返到 API 层。
- 旧隐藏行无法区分「当时未置顶」和「升级前已移除」，统一按未置顶处理；这是可接受的
  一次性降级。
- 恢复触发的置顶没有显式审计，管理员看到的是恢复审计；若未来需要区分，可再加
  `session_pin_audits.source`，不在本 ADR 范围。
- 容量在恢复瞬间可能被其他请求改变；advisory lock 保证同一用户的置顶/恢复串行，
  不会插入超过 `pin_limit`。

## 验证

- 默认：`534 passed + 42 skipped`；PG-only：`573 passed + 3 skipped`；
  PG+Redis：`576 passed`。
- `ruff check` / `ruff format --check` 208 files / `mypy app` 119 files 通过。
- 前端未改：29 files / 149 tests。
- 迁移 `0027` 往返：`upgrade head → alembic check → downgrade 0026 → upgrade head`。
- 用例：`tests/test_store_contract.py::_exercise_restore_pin`（含 `pin_limit=1` 的容量
  不足分支）、`test_sessions_api.py::test_sessions_pin_and_legacy_cursor` 断言恢复后
  仍置顶；PG 契约覆盖同逻辑。

## 待定

- 是否需要「恢复后置顶」的开关（部署级或用户级）。
- 是否需要在恢复审计里显式记录恢复了几个置顶。
- 置顶容量满时是否给前端一个「已恢复但未置顶」的提示。
