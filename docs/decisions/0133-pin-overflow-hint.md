# ADR-0133：置顶超限时给出明确提示

## 背景

[ADR-0093](0093-session-pin-limit-config.md) 允许部署通过 `ONCALL_SESSION_PIN_LIMIT`
调整置顶上限。配置调小后，既有置顶数据不会被自动清理，`pinned_count` 可能大于
`pin_limit`；`SessionList` 已按 `pinned_count >= pin_limit` 禁用未置顶行的置顶按钮，
但用户只能看到按钮变灰，不知道为什么、也不知道怎么恢复。

## 决策

1. 新增纯函数 `pinLimitOverflow(pinned, limit)`：仅当 `pinned > limit` 时返回实际计数与上限，
   计数未知或上限非正数返回 `null`。
2. `SessionList` 计算溢出状态，传给 `SessionListChrome`；溢出时显示一条 `warn` 提示：
   「已置顶 X 个，超过上限 Y 个；新置顶已禁用，请取消置顶或调高上限。」
3. 提示使用 `<output>` 语义元素，随列表加载状态更新；不阻止取消置顶，也不新增清理动作。
4. 不自动取消超限置顶：删除用户数据应由用户或运维显式操作，避免升级/改配置时静默改变排序。

## 后果

- 配置调小后用户能看到原因与两条出路（取消置顶/调高上限），不必猜测按钮为何禁用。
- 计数在首屏列表响应里，多标签页仍可能短暂显示旧计数；此时新增置顶仍由后端 409 兜底。
- 不做一键清理超限置顶、不做容量管理页。

## 验证

- `pinLimitOverflow` 3 组用例：未超限/未知、超限、上限非正数。
- 前端 `pnpm test`、`tsc`、`oxlint`、`oxfmt --check`、`pnpm build`。

## 待定

- 是否提供「一键取消最早置顶直到不超限」；需要明确排序与审计，暂不做。
