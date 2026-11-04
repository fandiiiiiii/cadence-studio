# One image per model family (MOSS and Music Flamingo need different Transformers versions).
ARG BASE_IMAGE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/huggingface \
    PORT=8000 \
    MODEL_PATH=/repository \
    MODEL_FAMILY=flamingo \
    MAX_AUDIO_SECONDS=1200 \
    MAX_NEW_TOKENS=1024

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-flamingo.txt requirements-moss.txt /app/
ARG MODEL_FAMILY=flamingo
RUN if [ "$MODEL_FAMILY" = "moss" ] || [ "$MODEL_FAMILY" = "moss-thinking" ]; then \
      pip install --index-url https://download.pytorch.org/whl/cu128 torchaudio==2.9.1; \
      pip install -r /app/requirements-moss.txt; \
    else \
      pip install -r /app/requirements-flamingo.txt; \
    fi

COPY server.py /app/server.py
ENV MODEL_FAMILY=${MODEL_FAMILY}
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120"]
