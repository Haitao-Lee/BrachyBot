# Resource intent shortcut boundary

## Root cause

`resolve_report_request_action` treated any occurrence of report/报告 without a
generation keyword as a read. `classify_local_turn` then selected
`session_content_query`. All three chat entrypoints consumed that local policy
before the primary model could interpret the operation. Thus clearing a report
was acknowledged as opening a report; this was not a model comprehension failure.

## Architecture

Keep registered capability validation and explicit execution shortcuts. Resource
read shortcuts now require a complete positive command recognized by
`intent_boundary.canonical_resource_read`, not an arbitrary sentence containing
a noun and a verb. The same boundary applies to all Session content families.
Report generation shortcuts also require a complete canonical command.
Unknown words, edits, conditions, negation, mixed requests and long messages
abstain to the existing primary semantic function-calling path. No separate
classification model or network round-trip was added. Resource discovery is
not execution authorization. Unmatched report requests retain inspector and
controller access without pregranting mutation.

The normal, trace and streaming chat branches consume the same local policy.
The existing semantic runtime selects tools and parameters with context; the
normalizer does not replace a selected report.clear action with ui_content.
The controller preserves destructive confirmation metadata. No patient reports
were actually cleared during verification.

## Verification

238 tests passed across intent boundary, runtime contracts, lightweight streams,
response presentation, planning visual delivery, round7 regressions, screenshot
trace integration and semantic execution authorization. Three SWIG dependency
deprecation warnings remain. Added negative cases, multilingual canonical reads,
generation commands and a clear-tool normalization/confirmation contract.
Two preexisting exact asset-version assertions were updated to the versions
already shipped by the previous Data Tree grounding fix, without weakening the
assertions.

Remote microbenchmark: 1,000 local classifications took 0.5261 seconds on the
current host. This excludes imports, provider inference and tool/browser work;
it is not a user-visible latency guarantee.

## Boundaries

This does not replace every clinical/UI/provenance resolver or guarantee perfect
model interpretation. Existing domain-specific safety policies remain intact.
Unrecognized simple wording may now incur a primary-model call rather than an
incorrect zero-model acknowledgement. Provider failure must remain a failure,
not fall back to keyword execution. Live provider/browser end-to-end behavior
has not been exercised for a real destructive request.

Backend Python changes require a server process reload/restart. Code is merged
into the current remote working tree with hash guards; unrelated changes are
preserved. No server restart, git commit or push was performed in this change.
