# 11 · 开发环境

## 1. 前置依赖

| 工具 | 版本 | 用途 | 安装 |
|---|---|---|---|
| Docker Desktop | 最新 | Postgres / Redis | 官网 |
| Python | 3.12 | 后端 | `uv python install 3.12` |
| uv | 0.5+ | Python 依赖 | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node.js | 20+ | 前端 | 已装（v24 亦可） |
| pnpm | 9+ | 前端依赖 | `corepack enable && corepack prepare pnpm@latest --activate` |
| Git | 最新 | 版本控制 | 已装 |

## 2. 首次启动

```powershell
# 1. 进目录
cd E:\workspace\github\oncall

# 2. 环境变量
Copy-Item .env.example .env

# 3. 中间件
docker compose up -d

# 4. 后端
cd server
uv sync
uv run uvicorn app.main:app --reload --port 8000

# 5. 前端（新开一个终端）
cd web
pnpm install
pnpm dev
```

访问：

- 前端 http://127.0.0.1:5173
- 后端文档 http://127.0.0.1:8000/docs
- 健康检查 http://127.0.0.1:8000/api/health

## 3. 常用命令

无 `make` 时用 `pwsh -File scripts/dev.ps1 <target>`，或直接照抄 Makefile。

| 命令 | 作用 |
|---|---|
| `make up` / `make down` | 起停中间件 |
| `make api` | 起后端 |
| `make web` | 起前端 |
| `make fmt` | ruff + biome 格式化 |
| `make lint` | ruff + mypy + biome |
| `make test` | pytest + vitest |
| `make eval` | 跑评测出报告 |
| `make seed` | 灌演示数据 |

## 4. 项目约定

| 项 | 约定 |
|---|---|
| Python 包管理 | 只用 `uv`，不混用 pip/poetry |
| Python 风格 | ruff format + ruff check，行宽 100 |
| 类型 | 后端 mypy（至少 `app/agent`, `app/tools` 严格），前端 `strict: true` |
| 命名 | 表名复数蛇形；事件类型 `domain.action` 点分 |
| 提交信息 | `feat(agent): 增加 verify 节点重规划` / `fix(tools): 修正超时未取消协程` |
| 分支 | 一人开发直接 main；多人用 `feat/xxx` |
| 注释 | 只写"为什么"，不写"是什么" |

## 5. 排错

### Docker 起不来

```powershell
docker compose ps
docker compose logs postgres --tail=50
# 端口冲突：改 .env 的端口，或停掉本地已占用的 5432/6379
```

### 后端连不上库

- 确认 `ONCALL_DATABASE_URL` 用 `postgresql+asyncpg://`（不是 `postgres://`）
- 容器名解析：宿主机跑 uvicorn 用 `127.0.0.1:5432`；容器内跑用 `postgres:5432`
- pgvector 扩展未启用：`CREATE EXTENSION IF NOT EXISTS vector;`（W2 D8 才需要）

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

### Windows 路径 / 编码

- 所有文本文件 UTF-8（`.editorconfig` 已声明）
- 文件名避免中文，减少跨平台问题

## 6. 每天开工程序（建议）

```powershell
docker compose up -d      # 中间件常在，可跳过
cd server; uv sync        # 拉依赖变更
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## 7. 提交前检查

- [ ] `make fmt` 已跑
- [ ] `make lint` 无错
- [ ] `make test` 通过
- [ ] 改动涉及接口/事件 → 已更新 `docs/03-api-contract.md`
- [ ] 改动涉及表 → 已生成 alembic 迁移并人工审过
- [ ] 新增取舍 → 补一篇 ADR
