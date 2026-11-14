"""配置：根 `.env` 定位与生产密钥校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import (
    DEFAULT_SESSION_SECRET,
    ENV_FILE,
    MIN_SESSION_SECRET_LEN,
    Settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_file_points_to_repo_root() -> None:
    """从 server/ 启动也要读到仓库根的 .env（DB URL / JWT 密钥）。"""
    assert ENV_FILE == REPO_ROOT / ".env"


def test_dev_allows_default_secret() -> None:
    settings = Settings(env="dev", session_secret=DEFAULT_SESSION_SECRET)
    assert settings.session_secret == DEFAULT_SESSION_SECRET


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValidationError, match="ONCALL_SESSION_SECRET"):
        Settings(env="prod", session_secret=DEFAULT_SESSION_SECRET)


def test_production_rejects_short_secret() -> None:
    with pytest.raises(ValidationError, match=str(MIN_SESSION_SECRET_LEN)):
        Settings(env="prod", session_secret="x" * (MIN_SESSION_SECRET_LEN - 1))


def test_production_accepts_strong_secret() -> None:
    secret = "x" * MIN_SESSION_SECRET_LEN
    assert Settings(env="prod", session_secret=secret).session_secret == secret


def test_embedding_dim_must_match_vector_column() -> None:
    """kb_chunks.embedding 是 vector(1024)，换维度必须先迁移，不能在运行期截断。"""
    with pytest.raises(ValidationError, match="ONCALL_EMBEDDING_DIM"):
        Settings(embedding_dim=1536)
    assert Settings(embedding_dim=1024).embedding_dim == 1024


def test_admin_roles_are_parsed_from_csv() -> None:
    settings = Settings(admin_roles="admin, kb_admin")
    assert settings.admin_role_list == ["admin", "kb_admin"]


def test_rag_params_are_validated() -> None:
    with pytest.raises(ValidationError, match="ONCALL_RAG_RRF_K"):
        Settings(rag_rrf_k=0)
    with pytest.raises(ValidationError, match="ONCALL_RAG_CANDIDATES"):
        Settings(rag_top_k=10, rag_candidates=5)
    with pytest.raises(ValidationError, match="ONCALL_RAG_MIN_SCORE"):
        Settings(rag_min_score=1.5)
    with pytest.raises(ValidationError, match="ONCALL_RAG_BACKEND"):
        Settings(store_backend="memory", rag_backend="postgres")


def test_http_embedding_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="ONCALL_EMBEDDING_BASE_URL"):
        Settings(embedding_provider="http", embedding_base_url="")
    settings = Settings(embedding_provider="http", embedding_base_url="http://127.0.0.1:11434/v1")
    assert settings.embedding_provider == "http"


def test_recovery_params_are_validated() -> None:
    """阈值配成 0 会把活着的 run 当孤儿，必须在启动期拒绝。"""
    with pytest.raises(ValidationError, match="ONCALL_STALE_RUN_MIN"):
        Settings(stale_run_min=0)
    with pytest.raises(ValidationError, match="ONCALL_RECOVERY_INTERVAL_S"):
        Settings(recovery_interval_s=0)
    settings = Settings(stale_run_min=15, recovery_interval_s=30)
    assert (settings.stale_run_min, settings.recovery_interval_s) == (15, 30.0)


def test_retention_params_are_validated() -> None:
    """保留期是删除边界：配成 0 天会立刻清空事件，必须在启动期拒绝。"""
    with pytest.raises(ValidationError, match="ONCALL_EVENT_RETENTION_DAYS"):
        Settings(event_retention_days=0)
    with pytest.raises(ValidationError, match="ONCALL_MODEL_CALL_RETENTION_DAYS"):
        Settings(model_call_retention_days=0)
    with pytest.raises(ValidationError, match="ONCALL_RETENTION_INTERVAL_S"):
        Settings(retention_interval_s=0)
    with pytest.raises(ValidationError, match="ONCALL_RETENTION_BATCH"):
        Settings(retention_batch=0)
    with pytest.raises(ValidationError, match="ONCALL_RETENTION_MAX_BATCHES"):
        Settings(retention_max_batches=0)
    with pytest.raises(ValidationError, match="ONCALL_RUN_CONTENT_RETENTION_DAYS"):
        Settings(run_content_retention_days=0)
    with pytest.raises(ValidationError, match="ONCALL_SESSION_RESTORE_AUDIT_RETENTION_DAYS"):
        Settings(session_restore_audit_retention_days=0)

    # 事件里带着同一段回答正文：正文保留期短于事件保留期时，清了 runs 也白清
    with pytest.raises(ValidationError, match="必须 >= ONCALL_EVENT_RETENTION_DAYS"):
        Settings(event_retention_days=180, run_content_retention_days=90)
    # 升级场景：现场把事件保留期调到 365 天、没动正文保留期（默认 180）时必须拒绝，
    # 而不是静默把正文的删除时间从 180 推到 365
    with pytest.raises(ValidationError, match="ONCALL_RUN_CONTENT_RETENTION_DAYS"):
        Settings(event_retention_days=365)

    settings = Settings(_env_file=None)  # 只看代码默认值，不读本机 .env
    assert settings.event_retention_days == 180
    assert settings.model_call_retention_days == 180
    assert settings.run_content_retention_days == 180
    assert settings.session_restore_audit_retention_days == 365


def test_user_daily_budget_is_validated_and_converted_to_cents() -> None:
    """与全局预算同口径：0 = 不限，显式非零至少 1 分（ADR-0026）。"""
    with pytest.raises(ValidationError, match="ONCALL_USER_DAILY_BUDGET_CNY"):
        Settings(user_daily_budget_cny=-0.1)
    assert Settings(user_daily_budget_cny=0).user_daily_budget_cents == 0
    assert Settings(user_daily_budget_cny=1.5).user_daily_budget_cents == 150
    # 小于半分也至少按 1 分算：配了 0.001 元不该等于没配
    assert Settings(user_daily_budget_cny=0.001).user_daily_budget_cents == 1
