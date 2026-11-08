# OnCall —— 常用命令
# Windows 无 make 时执行：pwsh -File scripts/dev.ps1 <target>
# 或直接照抄下方命令。

.PHONY: help up down logs migrate api web dev install fmt lint test eval seed clean

help:
	@echo "up      起中间件 (postgres + redis)"
	@echo "down    停中间件"
	@echo "migrate 应用数据库迁移 (alembic upgrade head)"
	@echo "install 安装前后端依赖"
	@echo "api     起后端 (8000)"
	@echo "web     起前端 (5173)"
	@echo "fmt     格式化 (ruff + oxfmt)"
	@echo "lint    静态检查"
	@echo "test    跑测试"
	@echo "eval    跑评测并生成报告"
	@echo "seed    灌演示数据"
	@echo "clean   清理构建产物"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	cd server && uv run alembic upgrade head

install:
	cd server && uv sync
	cd web && pnpm install

api:
	cd server && uv run uvicorn app.main:app --reload --port 8000

web:
	cd web && pnpm dev

fmt:
	cd server && uv run ruff format . && uv run ruff check --fix .
	cd web && pnpm exec oxfmt

lint:
	cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd web && pnpm exec oxlint && pnpm exec oxfmt --check

test:
	cd server && uv run pytest -q
	cd web && pnpm test

eval:
	cd server && uv run python -m app.eval.runner

seed:
	cd server && uv run python -m app.seed.generate

clean:
	rm -rf web/dist server/.venv/.cache .pytest_cache
