#!/bin/sh
# 容器启动：先迁移，再按需灌演示数据，最后启动 API。
# ONCALL_SEED_DEMO=true 只用于演示/面试环境；生产必须显式设为 false，
# 否则每次重启都会把 seed 语料 upsert 回知识库。
set -eu

alembic upgrade head

if [ "${ONCALL_SEED_DEMO:-false}" = "true" ]; then
    echo "[entrypoint] seeding demo data (ONCALL_SEED_DEMO=true)"
    python -m app.seed.generate --db
fi

exec "$@"
