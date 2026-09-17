# Hidden-target visual evidence and language consistency

Base: remote BrachyBot HEAD `09151749c`, including its existing dirty worktree.
Do not deploy this staging directory over a newer checkout: merge by file.

## Causes confirmed in code and tests

- Provider-selected screenshot calls could omit the typed locate contract and
  stable subject, even when the question asked where an object was.
- Locate preservation prevented hidden objects from being displayed for capture.
- Annotation visibility checks rejected marks but did not reject plausible,
  ungrounded prose. A warning appended to that prose contradicted the answer.
- The mixed-language detector counted Latin letters instead of words: English
  UI labels could outweigh the Chinese sentence around them.
- A follow-up naming Data Tree as the viewing surface replaced the antecedent
  guide subject with the surface itself.

## Changes

- Normalize screenshot location requests through the existing whole-request
  resolver, using the actual user turn and user-only antecedent context.
- Treat “在 data tree 的哪里呢” as a surface-qualified follow-up, without
  allowing unknown explicit objects to borrow the previous subject.
- Capture the real controllable Data Tree row before revealing an object.
- Temporarily reveal the resolved target and necessary parent nodes, including
  canonical CTV/OAR/needle/seed/trajectory collections. Frame only loaded scene
  objects through the existing verified focus path; never generate a missing mesh.
- Annotate immutable captures before restoring visibility. Restore state on
  upload failure, preserve unrelated node choices, and protect temporary
  presentation changes from periodic checkpoint writes.
- Use deterministic manifest-derived replies for location evidence. Describe
  Data Tree visibility separately from 3D visibility; explicitly report stale or
  unverified objects. Protect the durable backend reply as well as frontend text.
- Fix mixed Chinese/English UI-label detection and inherit the real parent
  request language in hidden image-analysis continuations.
- Keep report and monitor captures outside automatic locate reveal behavior.

## Verification

- 175 Python tests passed, 3 existing SWIG deprecation warnings, across language,
  screenshot, annotation, semantic authorization, response presentation, case
  result, and planning visual-delivery contracts.
- Expanded set including report progress: 176 passed, 1 failed. The failure is
  `test_report_capture_status_is_scoped_to_the_canonical_capture_promise`; both
  tested report-editor code and test are unchanged from HEAD (`git diff
  --exit-code HEAD` verified). This patch does not claim to repair that failure.
- Node executed the actual reveal/restore helpers and async capture orchestrator:
  hidden tree capture precedes visible viewer capture; annotation runs before
  restore; success and simulated upload failure both restore original state.
- JavaScript syntax checks passed.
- Remote concurrent presentation-write-lock changes were merged and preserved.

These are automated code/runtime-contract checks, not a live authenticated
browser replay of the user's patient session. Clinical geometry and planning
algorithms are unchanged. Existing stored screenshots are not rewritten.

Tests: `python -m pytest -q tests/test_visual_location_visibility.py`; browser
contract harness: `node tests/test_visual_location_visibility.cjs web/app/static/js`.
