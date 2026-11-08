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
