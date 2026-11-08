# 09 · 私有化部署

> 长沙的客户（制造业、医疗、政企）最在意的不是模型多强，是**数据不出内网、能装上、出问题有人兜**。

## 1. 三种部署形态

| 形态 | 资源 | 适用 | 模型 |
|---|---|---|---|
| 演示版 | 8C16G | 面试演示、POC | 云 API 或 Ollama 7B |
| 标准私有化 | 16C32G | 中型企业 | 本地 vLLM 7B/14B 量化 |
| 离线信创 | 32C64G + 国产卡 | 政企 | 适配后的国产模型 |

## 2. 组件清单

| 组件 | 必需 | 说明 |
|---|---|---|
| PostgreSQL 16 + pgvector | ✅ | 业务 + 向量 + 事件 |
| Redis 7 | ✅ | 限流、预算、锁 |
| api（FastAPI） | ✅ | 无状态，可多副本 |
| web（静态资源） | ✅ | Nginx 托管 |
| 模型服务 | ✅ | 云 API / Ollama / vLLM 三选一 |
| Langfuse | ⭕ | 可选，替代方案是自研看板 |

## 3. 一键起

```bash
cp .env.example .env        # 改 DATABASE_URL / 模型地址
docker compose up -d
# 打开 http://<host>:8080
```

`docker-compose.yml` 里 `api` / `web` 两段在 W6 打开（现在注释着，避免开发期反复 build）。

## 4. 离线镜像

```bash
# 有网机器
docker compose build
docker save -o oncall-images.tar \
  oncall-api:latest oncall-web:latest pgvector/pgvector:pg16 redis:7-alpine

# 客户内网
docker load -i oncall-images.tar
docker compose -f docker-compose.offline.yml up -d
```

配套交付物：

```
delivery/
├─ oncall-images.tar
├─ docker-compose.offline.yml
├─ .env.template
├─ 部署手册.pdf
└─ 验收清单.xlsx
```

## 5. Mock 模式（演示的命门）

```env
ONCALL_MOCK_MODE=true
```

行为：

- 模型返回**预置的确定性响应**（不是随机假数据），保证演示可复现
- 工具走**内置假数据**（`server/app/seed/`）
- 事件流、审批、成本计量全部照常执行

> 目的：面试官/客户拿到仓库，`docker compose up` 就能看到完整链路，不需要 key、不需要联网。这是开源项目的第一印象分。

## 6. 信创适配说明（写文档就够，别真去适配）

| 项 | 现状 | 说明 |
|---|---|---|
| 操作系统 | 待验证 | 麒麟 V10 / 统信 UOS；容器化后主要依赖内核版本与 cgroup v2 |
| CPU | 待验证 | 鲲鹏/飞腾（ARM64）；镜像需 multi-arch |
| 数据库 | 可替换 | 达梦/人大金仓；需替换 SQLAlchemy 方言，pgvector 不可用 → 换 Qdrant |
| 模型 | 可替换 | 国产模型需 OpenAI 兼容网关 |
| 浏览器 | 已兼容 | 政企常配 Chrome 90+，注意别用太新的 CSS |

> 这一节的价值：**证明你知道信创的门槛在哪**，而不是假装能一键适配。面试时说"容器化后主要是内核与架构问题，数据库方言和向量库是真正的替换点"，比说"我们支持信创"可信。

## 7. 资源与容量

| 项 | 单机 8C16G 实测目标 |
|---|---|
| 并发对话 | ≥ 20 |
| 检索 QPS | ≥ 30（5 万 chunk） |
| 事件写入 | ≥ 200 条/s |
| 冷启动 | ≤ 30s |

压测脚本：`server/app/eval/loadtest.py`（W6 D27 产出），报告附在 README。

## 8. 运维

| 场景 | 方案 |
|---|---|
| 日志 | 结构化 JSON → 文件；可选 Loki |
| 指标 | `/metrics`（Prometheus 格式），至少暴露：run 数、失败率、p95、token 消耗 |
| 备份 | `pg_dump` 每日 + 事件表按月归档 |
| 升级 | 先跑 alembic 迁移 → 再滚动重启 api |
| 回滚 | 镜像 tag + 数据库迁移的 downgrade 脚本（每次迁移必须写 downgrade） |

## 9. 安全清单

- [ ] 所有对外接口鉴权，管理接口二次校验角色
- [ ] 工具白名单默认拒绝（未注册即拒）
- [ ] 身份字段不允许来自模型入参
- [ ] 上传文件类型与大小限制，解析在子进程（防 PDF 炸弹）
- [ ] 提示词注入防护：检索内容包 `<document>` 并声明非指令
- [ ] 审计日志保留 180 天
- [ ] `.env` 不入库，密钥不出现在日志
- [ ] 依赖漏洞扫描（`uv pip audit` / `pnpm audit`）

## 10. 验收清单（交付用）

- [ ] `docker compose up` 后 3 分钟内可访问
- [ ] mock 模式可完整演示三条剧本
- [ ] 断网 10s 恢复不丢消息
- [ ] 越权用例 100% 拦截
- [ ] 成本看板数据与 `model_calls` 一致
- [ ] 备份恢复演练通过
