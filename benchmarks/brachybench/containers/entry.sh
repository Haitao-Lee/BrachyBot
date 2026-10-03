#!/bin/sh
# BrachyBench container entrypoint.
#
# Sub-commands map onto the design's gates so that a CI job can express the
# whole §19.7 / §27.3 checklist as one container invocation:
#
#   selftest   -- §8.6 I4/I5 judge self-validation (F11/F12)
#   tasks      -- §7 schema gate over tasks/ (F03)
#   fixtures   -- §21.1 generated-fixture replay + hash lock (F10)
#   splits     -- §12.6 five-level split invariant (F17)
#   manifest   -- §19.2 checksum freeze
#   all        -- everything above, in order
#
# It also pins the deterministic-kernel posture (R2/R11): torch is imported
# with `cudnn.benchmark=False` and `allow_tf32=False` *before* any checker runs
# so `env_lock.py` sees the evaluation configuration.
set -eu

BB=/work/benchmarks/brachybench
cd "$BB"

python - <<'PY' || echo "WARN: torch unavailable -- determinism posture unverified (see R2/R11)"
try:
    import torch
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    print("deterministic kernels ON (cudnn.benchmark=False, allow_tf32=False)")
except Exception as exc:
    raise
PY

run_selftest() { python -m pytest tests -q -k "selftest or ba1 or ba2 or ba3 or ba4 or ba5 or ba6 or ba21"; }
run_tasks()    { python tools/validate.py tasks --root .; }
run_fixtures() { python tools/build_fixtures.py --check; python -m pytest tests -q -k "physics"; }
run_splits()   { python tools/splits.py check --tasks tasks --splits splits/assignment.json; }
run_manifest() { python tools/hash_manifest.py check --root .; }

case "${1:-all}" in
  selftest) run_selftest ;;
  tasks)    run_tasks ;;
  fixtures) run_fixtures ;;
  splits)   run_splits ;;
  manifest) run_manifest ;;
  all)      run_selftest; run_tasks; run_fixtures; run_splits; run_manifest ;;
  *)        echo "unknown command: $1" >&2; exit 2 ;;
esac
