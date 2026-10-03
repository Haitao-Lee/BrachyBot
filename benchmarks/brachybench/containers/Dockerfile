# BrachyBench evaluation image (DESIGN §24.2 / §27.1).
#
# Reproducibility contract (§11.5): the image pins the numeric stack so that
# `tools/env_lock.py check` reports no drift, and it deliberately leaves the
# deterministic-kernel flags OFF at import time -- `plans/dose_pre/inference.py`
# sets `cudnn.benchmark = True` and `allow_tf32 = True`, which is exactly what
# R2/R11 say must be disabled during evaluation (see `containers/entry.sh`).
#
#   docker build -t brachybench:1.0 -f containers/Dockerfile .
#   docker run --rm -v "$PWD":/work brachybench:1.0 python benchmarks/brachybench/tools/validate.py tasks --root benchmarks/brachybench

FROM python:3.12-slim

LABEL org.opencontainers.image.title="BrachyBench" \
      org.opencontainers.image.description="Evaluation harness for the BrachyBench clinical-agent benchmark (DESIGN docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md)" \
      org.opencontainers.image.licenses="Apache-2.0 (code) / CC-BY-4.0 (synthetic data)" \
      org.opencontainers.image.version="1.0"

# Numeric stack pinned together -- `env_lock.py` verifies these exact versions.
RUN pip install --no-cache-dir \
      numpy==2.4.6 \
      scipy==1.15.3 \
      scikit-image==0.26.0 \
      SimpleITK==2.5.0 \
      pytest==9.1.1

# pydicom / torch are optional: the independent-parser and determinism probes
# degrade to "evidence gap" rather than passing without them (§8.6 I3).
RUN pip install --no-cache-dir pydicom==3.0.1 || true

WORKDIR /work
COPY benchmarks/brachybench /work/benchmarks/brachybench
COPY benchmarks/external /work/benchmarks/external

ENV PYTHONPATH=/work/benchmarks/brachybench:/work/benchmarks/external \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1

# force the deterministic-kernel posture that R2/R11 require
ENV TORCH_CUDNN_BENCHMARK=0 \
    TORCH_CUDNN_ALLOW_TF32=0 \
    TORCH_MATMUL_ALLOW_TF32=0

ENTRYPOINT ["/work/benchmarks/brachybench/containers/entry.sh"]
CMD ["selftest"]
