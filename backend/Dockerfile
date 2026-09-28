FROM docker.m.daocloud.io/library/python:3.12-slim AS build

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts/locked_target.py ./locked_target.py
RUN python -m pip install --no-cache-dir uv==0.11.26 packaging==26.2 && \
    uv sync --locked --no-dev --no-editable && \
    uv pip check --python .venv/bin/python && \
    uv export --locked --no-dev --no-hashes --no-header --no-annotate --no-emit-project > locked-requirements.txt && \
    python locked_target.py locked-requirements.txt > selected-dependencies.txt

FROM docker.m.daocloud.io/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
RUN test -n "$SOURCE_REVISION" && mkdir -p /data
COPY --from=build /app/.venv ./.venv
COPY --from=build /app/selected-dependencies.txt ./selected-dependencies.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
