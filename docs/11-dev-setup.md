# 11 · 开发环境

## 1. 前置依赖

| 工具 | 版本 | 用途 | 安装 |
|---|---|---|---|
| Docker Desktop | 最新 | Postgres / Redis | 官网 |
| Python | 3.12 | 后端 | `uv python install 3.12` |
| uv | 0.5+ | Python 依赖 | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node.js | 22.12+（本项目用 24） | 前端（Vite 8 / Vitest 5 / React Router 8 的下限） | 已装（v24 亦可） |
| pnpm | 10+ | 前端依赖（`packageManager` 已声明 10.34.3） | `corepack enable && corepack prepare pnpm@latest --activate` |
| Git | 最新 | 版本控制 | 已装 |

> 版本策略见 [decisions/0007](decisions/0007-dependency-versions.md)：前端依赖跟最新，TypeScript 用 6.0.3。
> TS 7 的原生编译器不提供 JS API，`openapi-typescript` 无法运行，因此 7.0 暂缓。

## 2. 首次启动

```powershell
# 1. 进目录
cd E:\workspace\github\oncall

# 2. 环境变量（后端读仓库根 .env：core/config.py 用绝对路径，从 server/ 启动也生效）
Copy-Item .env.example .env

# 3. 中间件
docker compose up -d

# 4. 后端
cd server
uv sync --extra rag
uv run alembic upgrade head
uv run python -m app.seed.generate --db   # 50 篇知识库 + 200 资产 + 500 工单
uv run uvicorn app.main:app --reload --port 8000

# 5. 前端（新开一个终端）
cd web
pnpm install
pnpm dev
```

> 跑测试/迁移检查需要开发依赖：`uv sync --extra dev --extra rag`（CI 还装 `--extra agent` 以通过 mypy）。
> `rag` extra 只有 `pypdf` + `python-docx`；PDF/DOCX 上传需要它，只跑单测可不装。

访问：

- 前端 http://127.0.0.1:5173
- 后端文档 http://127.0.0.1:8000/docs
- 健康检查 http://127.0.0.1:8000/api/health

### 2.1 签发本地 token

v1 不接 SSO，除 `/api/health` 与 OpenAPI 文档外，业务接口都要 Bearer token（见 [docs/03](03-api-contract.md) §0）。
在 `server/` 目录执行（若在仓库根，先 `cd server`）：

```powershell
uv run python -m app.cli token --user u_102 --roles employee
# 输出一串 JWT，复制到前端右上角「设置 Token」，或 curl 里加 -H "Authorization: Bearer <token>"

# 上传/重建知识库需要管理员角色（ONCALL_ADMIN_ROLES 默认 admin）
uv run python -m app.cli token --user admin_1 --roles admin

# 审批人：写操作审批用（不能审批自己发起的）
uv run python -m app.cli token --user u_900 --roles approver
```

上传一个文档验证 RAG 链路（`server/` 下执行）：

```powershell
$token = "<admin token>"
curl.exe -X POST http://127.0.0.1:8000/api/admin/kb/documents `
  -H "Authorization: Bearer $token" `
  -F "file=@seed_data/kb/kb-vpn-troubleshooting.md"
# 返回 document + chunks（含 heading_path），再用 employee token 问「VPN 连不上怎么办」
```

> 知识库为空时先跑 `uv run python -m app.seed.generate --db`；内存模式首次检索会自动载入 seed 语料。

## 3. 本机 Docker 方案（WSL + docker.io，无 Docker Desktop）

本机情况：**没有装 Docker Desktop**（它需要管理员权限，且 2025-06 已被卸载），但 WSL 2.3.26 可用。因此用「导入 Ubuntu 根文件系统 + 在 WSL 内装 docker.io」的方案，**全程不需要管理员权限**。

已完成的一次性准备（记录备查）：

| 步骤 | 做法 |
|---|---|
| 1. 准备 rootfs | 下载 `ubuntu-base-24.04.3-base-amd64.tar.gz`（29MB，无管理员也能下） |
| 2. 注册发行版 | `wsl --import Ubuntu E:\wsl\Ubuntu <tar> --version 2`（导入，非安装） |
| 3. 装 Docker | `wsl -d Ubuntu -u root -- bash /mnt/e/workspace/github/oncall/scripts/wsl-setup.sh` |
| 4. 镜像加速 | 脚本写入 `/etc/docker/daemon.json`（daocloud / 1ms.run / xuanyuan） |

脚本做了什么：换 aliyun 镜像源 → 引导装 CA 证书 → 装 `docker.io` + `docker-compose-v2` → 写镜像加速器 → 启动 `dockerd`（无 systemd，用 nohup 兜底）。

### 日常使用

```powershell
pwsh -File scripts/dev.ps1 docker-up     # 确保 dockerd 在线 + compose up -d
pwsh -File scripts/dev.ps1 docker-ps     # 看容器状态
pwsh -File scripts/dev.ps1 docker-logs   # 跟日志
pwsh -File scripts/dev.ps1 docker-down
```

> 不要用 `make up` —— Makefile 假设宿主机有 docker CLI，本机没有。`docker-*` 系列会经 WSL 执行。

### 注意

- WSL 空闲会自动关虚拟机，`dockerd` 随之停止。`docker-up` 已经内置“守护进程不在就拉起来”的逻辑，直接敲即可
- 容器端口通过 WSL2 localhost 转发暴露给 Windows，所以 Windows 侧的 `127.0.0.1:5432 / 6379` 依然可用
- 若以后装了 Docker Desktop，把 `Makefile` 里的 `up/down` 用起来即可，`docker-*` 可以不用
- WSL 磁盘文件在 `E:\wsl\Ubuntu\ext4.vhdx`，想回收空间可 `wsl --shutdown` 后压缩

## 4. 常用命令

无 `make` 时用 `pwsh -File scripts/dev.ps1 <target>`，或直接照抄 Makefile。

| 命令 | 作用 |
|---|---|
| `make up` / `make down` | 起停中间件 |
| `make migrate` | `alembic upgrade head`（DSN 取 `ONCALL_DATABASE_URL`） |
| `make api` | 起后端 |
| `make web` | 起前端 |
| `make fmt` | ruff + oxfmt 格式化 |
| `make lint` | ruff check + ruff format --check + mypy + oxlint + `oxfmt --check` |
| `make test` | pytest + vitest |
| `make eval` | 跑 50 条评测出报告（内存知识库，不依赖数据库） |
| `make eval-classify` | 跑 50 条意图分类评测（确定性规则，不需要数据库/模型） |
| `make seed` | 生成演示数据并写入 Postgres（需先 `make migrate`） |
| `make reap` | 回收进程中断的 `running` run（只收敛状态；先 `cd server && uv run python -m app.cli reap --dry-run` 看候选） |

### 4.1 数据库迁移与测试库

首次拉起中间件后必须建表，否则 `POST /api/chat/stream` 会返回 `503`：

```bash
cd server
uv run alembic upgrade head
uv run alembic check          # 模型与迁移是否漂移
```

Postgres 契约测试默认跳过；想跑真库测试，先建一个可清空的测试库，再指定 DSN：

```powershell
# 用 compose 里的容器建库（一次性）
# 注意：本机没有 docker CLI，改用 WSL 执行（compose 里 container_name 是 oncall-postgres）：
wsl -d Ubuntu -u root -- bash -lc "docker exec oncall-postgres psql -U oncall -d oncall -c 'CREATE DATABASE oncall_test'"
# 有 Docker Desktop 时：docker compose exec postgres psql -U oncall -d oncall -c "CREATE DATABASE oncall_test"

cd server
$env:ONCALL_TEST_DATABASE_URL = "postgresql+asyncpg://oncall:oncall@127.0.0.1:5432/oncall_test"
uv run pytest -q               # 含 Postgres 契约、并发 seq、pgvector 检索
```

> 测试会 `drop_all` / `create_all`，**不要指向开发库**；pgvector 扩展由 fixture 自动创建。

## 5. 项目约定

| 项 | 约定 |
|---|---|
| Python 包管理 | 只用 `uv`，不混用 pip/poetry |
| Python 风格 | ruff format + ruff check，行宽 100 |
| 前端样式 | 只用 Tailwind CSS utility class，颜色/字号走 `src/styles/global.css` 的 `@theme` 令牌，不写裸色值 |
| 前端风格 | oxlint（规则见 `web/.oxlintrc.json`）+ oxfmt（`web/.oxfmtrc.json`），行宽 100，单引号 |
| 类型 | 后端 mypy（至少 `app/agent`, `app/tools` 严格），前端 `strict: true` |
| 命名 | 表名复数蛇形；事件类型 `domain.action` 点分 |
| 提交信息 | `feat(agent): 增加 verify 节点重规划` / `fix(tools): 修正超时未取消协程` |
| 分支 | 一人开发直接 main；多人用 `feat/xxx` |
| 注释 | 只写"为什么"，不写"是什么" |

## 6. 排错

### Docker 起不来

```powershell
docker compose ps
docker compose logs postgres --tail=50
# 端口冲突：改 .env 的端口，或停掉本地已占用的 5432/6379
```

### 后端连不上库

- 确认 `ONCALL_DATABASE_URL` 用 `postgresql+asyncpg://`（不是 `postgres://`）
- 容器名解析：宿主机跑 uvicorn 用 `127.0.0.1:5432`；容器内跑用 `postgres:5432`
- pgvector 扩展未启用：`CREATE EXTENSION IF NOT EXISTS vector;`（W2 起知识库表依赖它；迁移 0003 也会自动建）

### 前端 404 / CORS

- Vite 已配 `/api` 代理到 `127.0.0.1:8000`，前端请求写 `/api/xxx` 不要写全域名
- 若改端口，同步改 `web/vite.config.ts` 的 proxy 与 `.env` 的 `ONCALL_CORS_ORIGINS`

### SSE 一次性返回（不流式）

- Nginx 缓冲导致：加 `proxy_buffering off;` 和响应头 `X-Accel-Buffering: no`
- 浏览器 devtools 看不到逐条：确认用的是 `fetch` + `ReadableStream`，不是 axios

### uv sync 慢

```powershell
$env:UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
uv sync
```

### alembic 报 `UnicodeDecodeError: 'gbk' codec can't decode`

- 原因：`alembic.ini` 里有 UTF-8 中文注释，而 alembic 用 **locale 编码**（中文 Windows = cp936）读取该文件
- 解决：`alembic.ini` 保持**纯 ASCII**（当前已是）；`PYTHONUTF8=1` 对它无效，别白试
- 同理：任何 `.ini` / `.cfg` 配置都不要写中文

### Windows 路径 / 编码

- 所有文本文件 UTF-8（`.editorconfig` 已声明）
- 文件名避免中文，减少跨平台问题

## 7. 每天开工程序（建议）

```powershell
docker compose up -d      # 中间件常在，可跳过
cd server; uv sync --extra dev --extra rag   # 拉依赖变更
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## 8. 提交前检查

- [ ] `make fmt` 已跑
- [ ] `make lint` 无错
- [ ] `make test` 通过
- [ ] 改动涉及接口/事件 → 已更新 `docs/03-api-contract.md`
- [ ] 改动涉及表 → 已生成 alembic 迁移并人工审过
- [ ] 新增取舍 → 补一篇 ADR
