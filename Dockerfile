FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.14-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
# libGL/libglib are needed by opencv, which the OCR fallback imports.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app /app
RUN python manage.py collectstatic --noinput
EXPOSE 8000
# sqlite and uploads live in the image: single instance + mount /app/db.sqlite3 and /app/media
# if they must survive a redeploy.
VOLUME ["/app/media"]
CMD ["sh", "-c", "python manage.py migrate && gunicorn parser.wsgi --bind 0.0.0.0:8000 --timeout 300"]
