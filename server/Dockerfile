# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.12-slim AS builder

WORKDIR /app
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runner

WORKDIR /app

# إنشاء مستخدم غير ميزة (Rule 13.4)
RUN groupadd -g 10001 secretary && \
    useradd -u 10001 -g secretary -s /bin/false -m secretary && \
    mkdir -p /data /exports /tmp && \
    chown -R 10001:10001 /data /exports /tmp

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
COPY alembic.ini /app/
COPY config /app/config/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
