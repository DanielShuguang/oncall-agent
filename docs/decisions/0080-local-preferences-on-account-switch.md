# ADR-0080：切换账号时清理本地偏好

- 状态：已采纳
- 日期：2026-11-16
- 关联：ADR-0075、ADR-0078、ADR-0079

## 背景

会话页与审计页会把少量界面偏好写入 `localStorage`：

- `oncall.last-session.v1`（ADR-0079）
- `oncall.audit-filters.v1`（ADR-0078）
- `oncall.audit-date-preset.v1`（ADR-0075）

这些键是全局的，不带账号命名空间。`TokenDialog` 保存新 token 时只调用
`setToken()`，不清理偏好。同一浏览器从一个账号切到另一个账号时，下一位用户会
继承上一位的：

- 审计页用户/会话过滤值（界面上会直接显示别人的 `user_id`/`session_id`）；
- 上次会话 id（因首屏可见性检查，不会打开不属于自己的会话，但 id 仍会短暂出现
  在恢复逻辑里）；
- 日期预设。

ADR-0078 的「待定」已明确记录「是否在退出登录或切换账号时清空本地过滤」。本
ADR 先采用最小、可验证的方案。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 不处理 | 否决 | 跨账号残留过滤值，至少是标识泄露与误操作风险 |
| 每次保存 token 都清空 | 否决 | 同一用户 token 续签会丢掉全部偏好，代价过大 |
| 按 `sub` 命名空间化存储 | 暂缓 | 需要改三个存储模块、兼容旧键、清理迁移；收益只是保留各账号偏好 |
| 退出登录时清空 | 暂缓 | 当前没有显式退出按钮；只清 token 时无法保证下一位用户不再看到旧值 |
| 切换 subject 时清空三个已知键 | 采纳 | 代码面小，不引入新表/迁移，直接消除跨账号残留 |

## 决策

1. **只解析、不验签**：`tokenSubject()` 从 JWT payload 取 `sub`，用于本地偏好归属
   判断；不参与鉴权，解析失败返回 `null`。
2. **subject 变化才清理**：`TokenDialog` 保存时比较新旧 token 的 subject；新 token
   有合法 subject 且与旧 subject 不同（旧 token 为空时也视为不同）时，调用
   `clearLocalPreferences()`。
3. **清理三个已知键**：会话、审计过滤、审计日期预设；不清理 `oncall.token`，也
   不动其他站点/应用的键。
4. **同一 subject 续签不清理**：token 过期后重新签发同一用户的 token，保留本地
   偏好。
5. **退出到空 token 不主动清理**：当前没有退出按钮；清空 token 后下一位用户登录
   时 subject 仍会变化并触发清理。
6. **旧全局键不迁移**：不按账号拆分存储，清理后偏好从默认值开始；ADR 的「记住」
   只在同一账号、同一浏览器内成立。

## 后果

- 同一浏览器切换账号后，上一位的会话/审计过滤和日期预设不会带到下一位。
- 切换回原账号不会恢复之前的偏好；这是「清理」而非「按账号隔离」的代价。
- 不是安全边界：JWT 客户端可伪造，`localStorage` 也可被用户直接修改；本方案只
  解决正常账号切换时的误继承。
- 没有 `sub` 的 token（非 JWT 或手工构造）无法可靠判断归属；下一次保存带 `sub`
  的 token 仍会触发清理。
- 没有服务端存储或迁移；偏好仍不跨设备。

## 验证

- 新增 `web/src/api/tokenSubject.test.ts`：正常 `sub`、去空白、缺失/非字符串、
  非 JWT/坏 base64/坏 JSON。
- 新增 `web/src/lib/localPreferences.test.ts`：只清三个已知键、保留无关键；无存储
  时静默跳过。
- `pnpm exec tsc --noEmit` 通过；`pnpm test -- --run` **114 tests / 24 files**；
  `pnpm lint` 0 warnings/0 errors（85 files/231 rules）；`pnpm format:check` 93 files；
  `pnpm build` 通过（2898 modules，257ms）。
- 后端未改：默认 506+40 / PG 543+3 / Redis 546；ruff 196 / mypy 114。

## 待定

- 是否改为按 `sub` 命名空间保存，保留各账号偏好。
- 是否增加显式「退出登录」并同时清理三个键。
- 多管理员共用同一浏览器 profile 时是否加提示。
