# syntax=docker/dockerfile:1
# 私有化 API 镜像：固定 Python/uv 版本，只装运行所需依赖（含 PDF/DOCX 解析）。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# uv 版本与本地开发保持一致，避免锁文件解析差异
RUN pip install --no-cache-dir uv==0.11.19

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# rag extra 提供 pypdf / python-docx；不装 torch / sentence-transformers
RUN uv sync --frozen --no-dev --extra rag \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 oncall \
    && chown -R oncall:oncall /app

USER oncall
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
