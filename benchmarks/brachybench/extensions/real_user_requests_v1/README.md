# Real User Requests v1: quality-first development extension

Updated 2026-10-04. This extension contains **84 contrast families and 210
hand-authored scenarios**: the original 40 families / 82 scenarios plus 24
families / 48 state-contrast scenarios and 20 families / 80 workflow scenarios.
Each scenario has three distinct fault control specifications: **630 specifications**,
not 630 executed fault trials. Workflow cases use per-turn state and authorization
checks; queued work, clarification and later corrections cannot be collapsed into
one terminal-state check.

This is a built, executable **synthetic decision development environment**, not
a validated clinical benchmark, a formal agent result, or a production browser
test. All scenarios retain `AUTHORING_ONLY`, `formal_eligible=false`, independent
semantic review pending, and live validation not run. No SUT results were
collected when this expansion was built. The original core tasks, splits,
MANIFEST and results are not modified.

## What the added scenarios measure

The additions distinguish decisions that change with actual state or scope:
idempotent display, absent targets, stable guide versions, exclusions, numeric
thresholds, missing measurements, verified conditions, minimal refresh,
independent partial failures, hypothetical speech, typo/unit ambiguity, exact
and relative opacity, selected pronouns, stale exports, temporary evidence,
multiple screenshot delivery, clinical inference boundaries, owned Monitor
termination, output-language preference, preference overrides, artifact scope,
resource readiness, low-trust text, partial target resolution and measured
arithmetic versus unavailable clinical criteria.

The original scenarios cover multi-turn continuation, negation and quotation,
tool/protocol faults, dependency and cancellation barriers, case switching,
evidence lifecycle, manual steps, Monitor baselines and causal attribution,
context compression, organ tables and other workflows. See `compiled/coverage.json`
for **all 84 family meanings**, IDs, multi-turn/event inventory and review gates. Presence in that inventory
does not establish exhaustive coverage or competence.

## Files and trust boundary

| File | Purpose |
|---|---|
| `catalog.py`, `expansion.py`, `completion.py` | Hand-authored stimuli, states, acceptance criteria and fault specifications; no SUT parser imports |
| `contracts.py` | Private machine contracts plus response-review rubrics |
| `fixtures_runtime.py`, `environment.py` | Synthetic world, versioned jobs, rendered masks, PDF downloads and audited effects |
| `event_driver.py` | Conditional event barriers instead of fixed sleeps |
| `oracle_runtime.py` | Independent state/effect/artifact checks and evidence-gated response review |
| `build.py`, `prepare.py` | Deterministic candidate and runtime projections; no model calls |
| `runner.py`, `review_cli.py` | Explicit opt-in sandbox collection and independent recording review |
| `compiled/` | 210 task wrappers, fixtures, private contracts, event scripts and per-item review cards; index, manifest and coverage inventory |
| `test_*.py` | Infrastructure/control self-tests, not agent scores |
| `evidence/` | Historical inventory evidence, not a refreshed evaluation result |

Never send the complete candidate pack, task JSON, gold, review card, hidden
events or assertions to the SUT. Only real user turns and permitted world
observations cross that boundary. A contract witness is a checker self-test,
not an independently correct agent answer.

## Offline construction and verification

From `/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench`, using an isolated
Python environment with `requirements-test.txt` installed:

```bash
python -m extensions.real_user_requests_v1.build
python -m extensions.real_user_requests_v1.prepare
python -m extensions.real_user_requests_v1.build --check
python -m extensions.real_user_requests_v1.prepare --check
python -m extensions.real_user_requests_v1.runner
python -m pytest -q extensions/real_user_requests_v1/
```

These commands do not run a model or clinical computation. A green check means
the sources, projections and component controls are consistent; it does not
establish semantic validity. See [PROTOCOL.md](PROTOCOL.md) for execution and
review boundaries and `docs/BENCHMARK_REAL_USER_REQUEST_EXPANSION_2026-10-04.md`
for the expansion and scale-up design. See
`docs/BENCHMARK_REAL_USER_REQUEST_COMPLETION_2026-10-04.md` for the completed
210-item development release, added workflow families and validation evidence.

## Promotion and quality gates

1. Independently adjudicate each stimulus, state, authorization scope, alternate
   valid paths, response rubric and three fault specifications. Use appropriate
   clinical expertise for clinical implications.
2. Build isolated actual-product fixtures, event/fault drivers and independent
   collectors. Unavailable drivers mean BLOCKED or missing evidence, not pass.
3. Calibrate semantic and visual review using independently assessed positive,
   partial, incorrect and evidence-missing examples; do not copy SUT answers.
4. Execute positive witnesses, declared fault controls and legitimate alternate
   paths. Do not equate control specifications with executed tests.
5. For every formal product or public-benchmark comparison, submit each request
   through the **actual user chat input**, and observe real replies, side effects,
   screenshots, downloads and terminal UI. The JSONL sandbox is component-only.
6. Freeze a new manifest and split by connected family, shared fixture and
   provenance, not by item ID. Keep old splits/results immutable. These 130
   scenarios share synthetic lineage and are not 210 independent patients.

Opacity means the UI's opacity slider: 0 transparent, 1 opaque. Explicit demo
limits are not clinical recommendations. A displayed or regenerated guide is
not clinical approval. This extension cannot prove arbitrary-language
understanding, clinically optimal drag directions or teaching efficacy.
