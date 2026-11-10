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
    #: 单次调用的 HTTP 超时；网关按 provider 逐个 failover
    model_request_timeout_s: float = 20.0
    model_max_tokens: int = 512
    model_temperature: float = 0.2
    #: 价格单位「分 / 百万 token」；本地模型默认 0，云端按供应商账单覆盖
    cloud_price_in_cents_per_1m: int = 15
    cloud_price_out_cents_per_1m: int = 60
    local_price_in_cents_per_1m: int = 0
    local_price_out_cents_per_1m: int = 0
    #: 单 run 成本上限（与 agent.state.BUDGET_CENTS 同口径）
    run_budget_cents: int = 50

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
    #: 审批人角色；resolve 要求该角色且不能是发起人（docs/06 §7）
    approver_roles: str = "approver"
    approval_ttl_min: int = 10
    #: scope=session 的授权有效期；到期回到逐次审批
    approval_grant_hours: int = 8

    # 运行态
    session_secret: str = DEFAULT_SESSION_SECRET
    #: 事件（回放 + 审计）保留天数（ADR-0021）。docs/09 §9 要求审计日志 180 天，
    #: 30 天会让「可回放」和「可审计」都短于承诺；清理任务按整场 run 删事件。
    event_retention_days: int = 180
    #: 模型调用计量的保留天数：成本看板的数据源，过期后只保留 runs 上的汇总
    model_call_retention_days: int = 180
    #: run 正文（`runs.input/output`）的保留天数（ADR-0023）。到点后清空正文并写
    #: `runs.content_pruned_at`，只留运行摘要。必须 `>= event_retention_days`：
    #: `message.delta`/`message.completed` 里是同一段回答正文，事件还在时清 runs
    #: 等于没清（理由见 ADR-0023）；想更早删正文就同时调小事件保留期。
    run_content_retention_days: int = 180
    #: 保留清理任务扫描间隔
    retention_interval_s: float = 21600.0
    #: 保留清理：单批行数与每轮最多跑几批。一次扫描只删一批的话，
    #: 6 小时间隔下每天最多清 4 × batch 场 run（默认 800），跑量一大就追不上；
    #: 轮内循环到「取不满一批」或达到批次上限为止。
    retention_batch: int = 200
    retention_max_batches: int = 10
    #: 超过该时长没有任何事件的 running run 判定为进程中断（ADR-0017）。
    #: 必须明显大于单 run 时长上限（agent.state.RUN_TIMEOUT_S=120s），否则会误杀活着的 run。
    stale_run_min: int = 10
    #: 孤儿 run 回收任务扫描间隔
    recovery_interval_s: float = 60.0

    @model_validator(mode="after")
    def _validate_embedding_dim(self) -> Self:
        if self.embedding_dim != VECTOR_DIM:
            raise ValueError(
                f"ONCALL_EMBEDDING_DIM 必须是 {VECTOR_DIM}（与 kb_chunks.embedding 一致）；"
                "换维度需要先迁移表结构"
            )
        return self

    @model_validator(mode="after")
    def _validate_rag(self) -> Self:
        """检索参数直接决定打分与 SQL；非法值要在启动期拒绝，不能等到第一次请求。"""
        if self.rag_top_k < 1:
            raise ValueError("ONCALL_RAG_TOP_K 必须 >= 1")
        if self.rag_candidates < self.rag_top_k:
            raise ValueError("ONCALL_RAG_CANDIDATES 不能小于 ONCALL_RAG_TOP_K")
        if not 0.0 <= self.rag_min_score <= 1.0:
            raise ValueError("ONCALL_RAG_MIN_SCORE 必须在 [0, 1] 内")
        if self.rag_rrf_k < 1:
            raise ValueError("ONCALL_RAG_RRF_K 必须 >= 1（公式里有 k+1 作分母）")
        if self.kb_max_upload_mb < 1:
            raise ValueError("ONCALL_KB_MAX_UPLOAD_MB 必须 >= 1")
        if self.rag_backend == "postgres" and self.store_backend != "postgres":
            raise ValueError(
                "ONCALL_RAG_BACKEND=postgres 需要 ONCALL_STORE_BACKEND=postgres："
                "pgvector 与事件存储在同一个库"
            )
        if self.embedding_provider == "http" and not self.embedding_base_url.strip():
            raise ValueError("ONCALL_EMBEDDING_PROVIDER=http 时必须配置 ONCALL_EMBEDDING_BASE_URL")
        if self.approval_ttl_min < 1:
            raise ValueError("ONCALL_APPROVAL_TTL_MIN 必须 >= 1")
        if self.approval_grant_hours < 1:
            raise ValueError("ONCALL_APPROVAL_GRANT_HOURS 必须 >= 1")
        if not self.approver_role_list:
            raise ValueError("ONCALL_APPROVER_ROLES 至少配置一个角色")
        return self

    @model_validator(mode="after")
    def _validate_runtime(self) -> Self:
        """回收阈值配错会误杀活着的 run，保留天数配错会删掉不该删的数据，启动期就拒绝。"""
        if self.stale_run_min < 1:
            raise ValueError("ONCALL_STALE_RUN_MIN 必须 >= 1")
        if self.recovery_interval_s <= 0:
            raise ValueError("ONCALL_RECOVERY_INTERVAL_S 必须 > 0")
        if self.event_retention_days < 1:
            raise ValueError("ONCALL_EVENT_RETENTION_DAYS 必须 >= 1")
        if self.model_call_retention_days < 1:
            raise ValueError("ONCALL_MODEL_CALL_RETENTION_DAYS 必须 >= 1")
        if self.run_content_retention_days < 1:
            raise ValueError("ONCALL_RUN_CONTENT_RETENTION_DAYS 必须 >= 1")
        if self.run_content_retention_days < self.event_retention_days:
            raise ValueError(
                "ONCALL_RUN_CONTENT_RETENTION_DAYS 必须 >= ONCALL_EVENT_RETENTION_DAYS："
                "事件里带着同一段回答正文，事件没清时清 runs 等于没清"
            )
        if self.retention_interval_s <= 0:
            raise ValueError("ONCALL_RETENTION_INTERVAL_S 必须 > 0")
        if self.retention_batch < 1:
            raise ValueError("ONCALL_RETENTION_BATCH 必须 >= 1")
        if self.retention_max_batches < 1:
            raise ValueError("ONCALL_RETENTION_MAX_BATCHES 必须 >= 1")
        return self

    @model_validator(mode="after")
    def _validate_gateway(self) -> Self:
        """网关参数直接决定计费与限流，非法值不能在第一次调用时才暴露。"""
        if self.model_request_timeout_s <= 0:
            raise ValueError("ONCALL_MODEL_REQUEST_TIMEOUT_S 必须 > 0")
        if self.model_max_tokens < 1:
            raise ValueError("ONCALL_MODEL_MAX_TOKENS 必须 >= 1")
        if not 0.0 <= self.model_temperature <= 2.0:
            raise ValueError("ONCALL_MODEL_TEMPERATURE 必须在 [0, 2] 内")
        for name in (
            "cloud_price_in_cents_per_1m",
            "cloud_price_out_cents_per_1m",
            "local_price_in_cents_per_1m",
            "local_price_out_cents_per_1m",
            "run_budget_cents",
            "rate_limit_per_min",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"ONCALL_{name.upper()} 不能为负数")
        if self.run_budget_cents < 1:
            raise ValueError("ONCALL_RUN_BUDGET_CENTS 必须 >= 1")
        if self.daily_budget_cny <= 0:
            raise ValueError("ONCALL_DAILY_BUDGET_CNY 必须 > 0")
        if not self.mock_mode and not self.provider_names:
            raise ValueError("ONCALL_MOCK_MODE=false 时 ONCALL_MODEL_PROVIDERS 不能为空")
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
    def daily_budget_cents(self) -> int:
        """每日预算统一按「分」计算，避免浮点累计误差（R6）。"""
        return max(1, round(self.daily_budget_cny * 100))

    @property
    def cloud_configured(self) -> bool:
        return bool(self.cloud_base_url.strip() and self.cloud_model.strip())

    @property
    def local_configured(self) -> bool:
        return bool(self.local_base_url.strip() and self.local_model.strip())

    @property
    def admin_role_list(self) -> list[str]:
        return [r.strip() for r in self.admin_roles.split(",") if r.strip()]

    @property
    def approver_role_list(self) -> list[str]:
        return [r.strip() for r in self.approver_roles.split(",") if r.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
