FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .

RUN groupadd -r kbuser && useradd -r -g kbuser -m -d /home/kbuser kbuser
USER kbuser

ENV EMBEDDING__DEVICE=cpu

EXPOSE 8100

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
