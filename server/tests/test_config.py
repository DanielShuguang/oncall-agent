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
