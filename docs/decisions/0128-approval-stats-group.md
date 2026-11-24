# ADR-0128：审批统计分组按浏览器记住

## 背景

审批统计提供 `none` / `tool` / `approver` 三种分组（ADR-0051）；切到「按审批人」后刷新页面会回到不分组。ADR-0127 只解决了统计窗口，待定项明确问「是否把窗口偏好与统计分组一起记忆」。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 并入 `oncall.approval-stats-window.v1` | 不采纳：窗口与分组是两个维度，合在一起会让「看多长」与「按什么看」互相耦合。 |
| 并入自动刷新开关 key | 不采纳：刷新策略是运行态偏好，分组是查询维度。 |
| 独立 key，只接受 `none`/`tool`/`approver` | 采纳：默认 `none`；缺失/损坏/非法值回退 `none`；与窗口、开关、间隔互不影响。 |

## 决策

1. 新增 `oncall.approval-stats-group.v1`，值为 `none`/`tool`/`approver`；默认 `none` 不写 key（删除）；写入非法值时按 `none` 处理并删除。
2. `ApprovalsPage` 用 `readApprovalStatsGroup` 懒初始化 `statsGroup`；切换分组时先失效统计导出，再写 key。
3. 切换账号由 `clearLocalPreferences` 清该 key，避免下一位用户继承上一位的分组视角。
4. 与列表状态、待办/已办切换、工具/审批人/日期筛选无关；不跨设备同步。
5. 不改 API/后端/迁移；只影响统计卡与统计导出的分组维度。

## 后果

- 默认仍不分组；管理员切到「按工具/审批人」后刷新/重开保持。
- 默认 `none` 不产生多余 key；本地偏好不参与权限判断。
- 自动刷新、窗口、过滤等行为不受分组偏好影响。

## 验证

- `approvalStatsGroup.test.ts` 3 用例：默认/非法回退、写 tool/none/非法删除、存储异常静默。
- `localPreferences.test.ts` 预置并断言切换账号清 key。
- 前端 `tsc`、`oxlint`、`vitest`、`oxfmt --check`、`pnpm build` 通过。

## 待定

- 是否把「分组」与「窗口」合并成一个页面视图偏好；本 ADR 继续保持两个独立 key。
- 是否按租户/团队共享默认分组；这需要服务端偏好，暂不做。
