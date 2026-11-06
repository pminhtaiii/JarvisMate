# syntax=docker/dockerfile:1
# Offline LifeMate integration image (specs/002-docker-integration).
# Build needs network for pinned wheels; runtime runs with --network none and mounts
# models, data and config read-only. No weights, datasets, secrets or training code
# are copied (see .dockerignore allowlist).
#
#   docker build -t lifemate-integration:dev .
#   docker run --rm --init --network none --gpus '"device=0"' \
#     --mount type=bind,src=/abs/models,dst=/models,readonly \
#     --mount type=bind,src=/abs/data,dst=/data,readonly \
#     --mount type=bind,src=/abs/config,dst=/config,readonly \
#     --mount type=bind,src=/abs/output,dst=/output \
#     lifemate-integration:dev --config /config/integration.toml

# python:3.11-slim-bookworm index digest read from Docker Hub on 2026-11-06 (not yet built).
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
FROM ${PYTHON_IMAGE}

# cu128 wheels cover Ampere (A30, sm_80) and newer GPUs; host driver must support CUDA 12.8.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HOME=/tmp/hf-home \
    CUBLAS_WORKSPACE_CONFIG=:4096:8

WORKDIR /opt/lifemate

# Dependencies first for layer reuse; torch comes from the selected CUDA wheel index.
COPY python/pyproject.toml python/pyproject.toml
COPY python/src python/src
RUN pip install --index-url "${TORCH_INDEX_URL}" torch==2.9.0 \
 && pip install "./python[inference]" \
 && pip freeze > /opt/lifemate/requirements.lock \
 && python -c "import lifemate.integration, lifemate.worker, transformers, lmformatenforcer"

# Split-matched organizer runtimes and catalogs, at the layout runtime.py expects.
COPY tools/train tools/train
COPY tools/test tools/test
COPY tools/train_tools_catalog.json tools/public_test_tools_catalog.json tools/

RUN useradd --create-home --uid 1000 lifemate
USER lifemate

ENTRYPOINT ["python", "-m", "lifemate.integration"]
CMD ["--help"]
