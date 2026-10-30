FROM python:3.12-slim
RUN useradd --create-home --uid 10001 ecm
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .
USER ecm
