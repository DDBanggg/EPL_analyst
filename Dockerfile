FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY sql ./sql

RUN python -m pip install --no-cache-dir --editable ".[dev]"

CMD ["python"]
