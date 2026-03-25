FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY . .

RUN uv pip install --system --no-cache .

RUN python -c "\
from tree_sitter_language_pack import get_parser; \
[get_parser(l) for l in ['python','java','go','javascript','typescript']]"

RUN groupadd -r kbuser && useradd -r -g kbuser -m -d /home/kbuser kbuser && \
    chown -R kbuser:kbuser /app && \
    chmod -R a+rwX /usr/local/lib/python3.12/site-packages/tree_sitter_language_pack/ && \
    mkdir -p /home/kbuser/.cache && chown -R kbuser:kbuser /home/kbuser/.cache

USER kbuser

ENV EMBEDDING__DEVICE=cpu
ENV EMBEDDING__BACKEND=onnx

EXPOSE 8100

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
