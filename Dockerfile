# HelpDesk Enterprise Copilot v12
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for chromadb/unstructured/native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libmagic1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python deps (layer cached separately)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source
COPY . .

# Runtime dirs
RUN mkdir -p /app/data /app/logs

# Hugging Face Spaces exposes a single public port via $PORT (default 7860).
ENV PORT=7860

EXPOSE 7860

CMD ["sh", "-c", "python scripts/run_api.py --prod --port ${PORT:-7860}"]