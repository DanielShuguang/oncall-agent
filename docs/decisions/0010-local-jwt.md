# ADR-0010 · 鉴权：本地签发 JWT（HS256），不接 SSO

- 状态：已采纳
- 日期：2026-11-09

## 背景

W1 D4 之前所有 run 都挂在固定用户 `u_102` 上。这带来两个直接问题：

1. **R9 无法执行**：身份字段只能来自服务端会话，但"会话"当时是硬编码
2. **run 无法隔离**：任何人都能读到别人的 run，审批（W3）也无法判断"谁在请求"

v1 是企业私有化交付，没有 IdP（SSO / OIDC）可接；但也不能没有身份。

## 方案对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| 继续硬编码 `u_102` | 零成本 | 讲不清权限边界；审批与归属校验无法做 |
| 接 SSO / OIDC | 企业真实形态 | 演示环境必须有 IdP；接入、回调、刷新都要时间 |
| 本地签发 JWT | 无外部依赖；身份来自服务端签发的 token | 没有登录页/刷新/吊销 |
| 本地 JWT + PyJWT | 成熟库 | 只为 sign/verify 多一个私有化镜像依赖 |
| Session Cookie | 浏览器友好 | SSE 跨域 + 私有化子路径下更麻烦；测试难写 |

## 决策

**本地签发 HS256 JWT，运维用 CLI 签发，API 用 `api/deps.get_identity` 校验。**

- 签发：`python -m app.cli token --user u_102 --roles employee`，默认 8 小时
- claims：`sub`、`roles`、`iat`、`exp`；密钥 `ONCALL_SESSION_SECRET`
- 校验：手写 HS256（`hmac` + `hashlib`），**只接受 `alg=HS256`**，签名用
  `hmac.compare_digest`，`exp` 过期即拒；错误统一 401，不告诉客户端哪一步失败
- 非 dev 环境：默认密钥或长度 < 32 字符直接拒绝启动（弱密钥等于没有鉴权）
- OpenAPI：用 `HTTPBearer(scheme_name="BearerAuth")` 声明安全方案，Swagger 可直接 Authorize
- 前端：token 存 `localStorage`，右上角「设置 Token」粘贴；没有登录页
- 归属：`GET /runs/*` 校验 `user_id`，别人的 run 返回 404

不引入 PyJWT：代码只有约 100 行，换来私有化镜像零新增依赖（R12）。

## 后果

- 正面：R9 可执行（身份只来自 token）；run 归属可校验；401 语义明确，前端能提示
- 负面：token 过期后要重新签发；没有吊销列表；不是企业 SSO 体验
- 缓解：默认 8 小时、内网部署；W3 审批人角色直接从 token `roles` 取；
  接 SSO 时只替换 `api/deps.get_identity`，store / runtime / 前端不动
- 安全边界：`ONCALL_SESSION_SECRET` 默认值只用于本地开发，**生产必须改**

## 面试话术

> v1 我做了本地签发的 JWT：身份只来自服务端签发的 token，模型和请求体里的
> `user_id` 一律不可信。没有引入 PyJWT，因为只需要 sign/verify，而私有化镜像
> 少一个依赖是实打实的收益。接 SSO 时只换认证依赖，run、工具治理、审批都不动。
