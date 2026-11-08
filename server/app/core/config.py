"""应用配置：全部通过 ONCALL_ 前缀的环境变量注入。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SESSION_SECRET = "dev-change-me"
MIN_SESSION_SECRET_LEN = 32
#: kb_chunks.embedding 的维度；换模型必须先迁移再改这里，不允许静默截断。
VECTOR_DIM = 1024

#: 仓库根目录的 .env。`make api` / README 都在 server/ 下启动 uvicorn，
#: 相对 cwd 的 ".env" 会读不到根配置（DB URL、JWT 密钥等），这里用绝对路径。
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ONCALL_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"
    api_prefix: str = "/api"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    database_url: str = "postgresql+asyncpg://oncall:oncall@127.0.0.1:5432/oncall"
    redis_url: str = "redis://127.0.0.1:6379/0"
    # memory 仅供测试/无库演示；生产默认 postgres，不做静默降级
    store_backend: Literal["postgres", "memory"] = "postgres"

    # 模型网关
    model_providers: str = "cloud,local"
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_model: str = ""
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_api_key: str = "ollama"
    local_model: str = "qwen2.5:7b"

    # 演示与限额
    mock_mode: bool = True
    daily_budget_cny: float = 5.0
    rate_limit_per_min: int = 30

    # RAG（W2）。rag_backend=auto：store 用 Postgres 时走 pgvector，否则内存索引。
    rag_backend: Literal["auto", "memory", "postgres"] = "auto"
    rag_top_k: int = 5
    rag_candidates: int = 20
    rag_min_score: float = 0.38
    rag_rrf_k: int = 60
    embedding_provider: Literal["hashing", "http"] = "hashing"
    embedding_dim: int = VECTOR_DIM
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "bge-m3"
    kb_max_upload_mb: int = 10
    #: 知识库管理接口要求的角色（W3 会换成 tables 里的权限矩阵）
    admin_roles: str = "admin"

    # 运行态
    session_secret: str = DEFAULT_SESSION_SECRET
    event_retention_days: int = 30

    @model_validator(mode="after")
    def _validate_embedding_dim(self) -> Self:
        if self.embedding_dim != VECTOR_DIM:
            raise ValueError(
                f"ONCALL_EMBEDDING_DIM 必须是 {VECTOR_DIM}（与 kb_chunks.embedding 一致）；"
                "换维度需要先迁移表结构"
            )
        return self

    @model_validator(mode="after")
    def _validate_session_secret(self) -> Self:
        """生产用弱密钥签发 token 等于没有鉴权，启动即拒绝（ADR-0010）。"""
        if self.env == "dev":
            return self
        if self.session_secret == DEFAULT_SESSION_SECRET:
            raise ValueError("ONCALL_SESSION_SECRET 仍是默认值，非 dev 环境拒绝启动")
        if len(self.session_secret) < MIN_SESSION_SECRET_LEN:
            raise ValueError(f"ONCALL_SESSION_SECRET 至少 {MIN_SESSION_SECRET_LEN} 个字符")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def provider_names(self) -> list[str]:
        return [p.strip() for p in self.model_providers.split(",") if p.strip()]

    @property
    def admin_role_list(self) -> list[str]:
        return [r.strip() for r in self.admin_roles.split(",") if r.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
