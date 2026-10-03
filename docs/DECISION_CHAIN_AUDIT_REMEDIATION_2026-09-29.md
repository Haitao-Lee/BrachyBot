# BrachyBot Decision and Execution Chain Audit and Remediation Record

Date: 2026-09-29. Audit baseline: LAN working tree `/home/lht/snap/brachyplan/BrachyBot`, HEAD `7aa6d2308`. Verified the working tree had no pre-existing uncommitted changes at the start and before delivery. This round does not modify the separate `BrachyBot-release`.

## 1. Conclusions and Scope

The problems confirmed this round are not merely insufficient vocabulary coverage, but contract breaks among request semantics, the model protocol, tool capability exposure, task dependencies, execution receipts, deduplication caching, and answer evidence. The remediation focuses on these shared boundaries, not on adding canned replies for a few user phrasings.

Main paths reviewed and modified:

`request_parse → turn_policy → provider tool calls → response_tools → execution_authorization / action_plan → clinical prerequisite normalization → streaming/non-stream execution → bounded evidence → response`

This report does not claim to have proven that the system can correctly handle all natural-language expressions. Real-model comprehension, end-to-end recovery of asynchronous browser receipts, multi-case/multi-version concurrency, and GPU clinical workflows still require separate acceptance. The conclusions below cover only code inspection, reproducible tests, and the explicitly listed fixes.

## 2. Confirmed and Remediated Issues

### D01 Quoted Content Escapes into an Executable Instruction After Sentence Splitting

- Cause: Splitting first on commas and similar symbols and then evaluating quotes separately destroyed the scope of a whole quotation; coordinate calculation for repeated quotation marks could also be wrong.
- Consequence: When a user pastes logs, paraphrases a command, or discusses code, the second half of a quotation could be taken as a new positive request.
- Fix: Scan quotation marks and Markdown code ranges in a single pass in the original-text coordinate system; build a quotation mask for the whole sentence before finding sentence boundaries. Supports apostrophes in English abbreviations, nested Chinese quotation marks, and conservative handling of unclosed quotations.
- File: `agent_runtime/request_parse.py`.

### D02 A Condition Constrains Only the First Following Action

- Cause: Comma-separated consequences reinitialized the condition state at each step.
- Consequence: When the condition was not met, subsequent report/guide generation could escape the condition constraint.
- Fix: A comma sequence in the same sentence retains the condition scope; periods, semicolons, and line breaks end the scope per the existing sentence-splitting contract. English condition words use token boundaries to avoid treating the `if` in `diff` as a condition word.
- Limitation: This is a verifiable local-scope fix, not automatic evaluation of arbitrarily complex natural-language conditions; an unmet condition still cannot grant execution permission.

### D03 Decimals Were Split into Sentences and Polite Requests Were Uniformly Treated as Read-Only Questions

- Cause: All periods were used as sentence boundaries; direct action requests such as "Could you generate the report?" were blocked solely because of the question mark.
- Fix: Periods between digits are no longer split; the grammatical form "modal request + direct action + object" is recognized, while method questions, alternative questions, negation, quotations, and conditions remain separately intercepted. Chinese sentence-initial modal constructions using "能不能/可不可以" no longer trigger negation merely because they contain "不能".
- The example tests include both explicit requests and cases that should not be executed directly, such as "如何生成", "生成报告还是导板", and "If needed".

### D04 Read-Only Local Classification in Compound Requests Removed Write-Operation Capabilities

- Cause: After detecting a planning query, only the read-only tool set was still offered for a compound sentence not yet fully interpreted.
- Fix: When the parse result clearly contains an unconditional positive operation, the semantic operation tool set is retained; whether a tool is actually executable still passes through the existing authorization and parameter checks, and tool visibility is not treated as authorization.
- File: `agent_runtime/turn_policy.py`.

### D05 Non-Streaming Execution Did Not Provide Tool Schemas to the Model

- Cause: The non-streaming loop passed `tools=None` when calling the provider, inconsistent with the streaming loop.
- Consequence: Tool selection lacked real names, parameter structures, and descriptions, and easily degraded into a text answer or non-executable output.
- Fix: The non-streaming loop supplies registry tool definitions and applies CT preconditions, internal sub-call, and turn policy filtering. The context budget is estimated together with the tool schemas; over-limit retries use the same set, and duplicate budget handling was removed.
- File: `agent_runtime/llm_runtime.py`.

### D06 Parameter and Step Identifiers Were Lost During Conversion Across Different Providers

- Cause: The two loops parsed independently, did not consistently handle the OpenAI `function.arguments` and native `name/input` formats, and did not carry through `key/depends_on`.
- Fix: Shared `decode_provider_call`. Invalid JSON, arrays, null, etc. can no longer become a default operation with empty parameters; they are kept as an explicit failed step and cannot be used to obtain authorization.
- Files: New `agent_runtime/step_execution.py`, plus `response_tools.py`, `execution_authorization.py`, and `llm_runtime.py`.

### D07 Task Order Was Mistaken for Prerequisite Success

- Cause: Only ordering was performed, with no unified execution receipt; the segmentation prerequisite inserted by clinical normalization also had no dependency identifier.
- Consequence: Downstream steps could still run after a prerequisite failed; alternatively, a single failure aborted the entire batch, losing even independent read-only queries.
- Fix: Both loops use the same `StepExecutionState`; the actually executable batch is topologically sorted, and downstream steps must obtain a prerequisite `succeeded` receipt. Missing, failed, and cyclic dependencies all block the affected steps, while independent tasks continue. Clinical normalization preserves existing step identifiers and adds dependencies to automatically inserted prerequisite steps.
- Failure and skip reasons are returned to the model as paired tool messages, rather than exiting early before appending the failure result.
- `accepted_pending_browser`, queued/running/dispatched, `completed=False`, etc. are recorded only as pending and cannot serve as completed preconditions.
- Limitation: This round did not add a cross-request scheduler for browser pending receipts; "preventing early execution" here cannot be interpreted as having completed automatic continuation for all asynchronous tasks.

### D08 Position Mix-Ups When Tools Share Names and Explicit/Implicit Step Identities Are Mixed

- Cause: During ordering, an explicit key did not consume the corresponding tool slot; a generated key could also conflict with an explicit key.
- Fix: Ordering tracks consumed slots; the actual batch preserves explicit identities and avoids generated-identity conflicts, and duplicate explicit identities are rejected for execution. Different steps cannot share the same execution receipt.
- Files: `action_plan.py`, `step_execution.py`.

### D09 A Post-Modification Query Was Mistaken for a Duplicate Call in the Same Round

- Cause: Deduplication was based only on tool name and parameters and did not include state-change boundaries.
- Consequence: The third step of "read → modify → read again" could be skipped, and the answer continued to use the old state.
- Fix: Introduced a per-round state epoch. The epoch advances after executing an operation that may change state, including failed write operations that may have partially taken effect; reads are repeated in a new epoch. Duplicate calls with no state change continue to be reused, preventing ineffective model loops.
- The cache preserves the distinction between pending and succeeded and does not treat a duplicate submission as completion.
- Limitation: This is a per-round execution-cache invalidation contract and does not replace the existing checks for case versions, browser state synchronization, and external concurrent edits.

### D10 Early Tool Evidence in the Same Round Was Dropped Outright by Context Compression

- Cause: Only the two most recent complete tool-call groups were retained, and early results after the third no longer entered the model context.
- Consequence: A compound task had already obtained evidence, yet the final answer claimed there was no data.
- Fix: The number of complete tool groups remains limited, but a bounded summary explicitly marked as data is retained for earlier same-round results and carried into the next compression; at most 16 entries at 400 characters per result, plus an argument summary (240 characters), to avoid losing object bindings after a same-named tool queries multiple objects. Expired call IDs are not kept in the summary, preserving valid pairing of the most recent complete tool call / tool result.
- Limitation: The bounded summary is not a complete database, and long tables must not be claimed as fully retained on its basis; when necessary, detailed results should still be obtained through a targeted query.

### D11 Final-Reply Sanitization Corrupted Decimals and Markdown

- Cause: Non-streaming answers were split on periods and rejoined with spaces, corrupting decimals, short answers, paragraphs, and tables.
- Fix: This destructive reassembly is no longer performed; the answer's original paragraphs and numbers are preserved. When a real answer exists, the user-specified format is no longer overwritten with a fixed large planning report, and the original fallback is kept only when the content is empty.
- Tool errors in string form are also extracted correctly and no longer uniformly degrade into a generic execution failed.

## 3. Implementation Principles

1. Semantic understanding may propose a plan, but protocol conversion must not lose objects, parameters, or step identity.
2. Tool visibility, tool authorization, tool submission, and tool completion are four distinct states.
3. Dependencies are satisfied by a success receipt, not by "being earlier in the order" or by a tool's returned success boolean alone.
4. Independent tasks may partially succeed; dependent tasks must not cross a failed or pending prerequisite operation.
5. Re-collect evidence after a state change, and the final answer must not treat an old query as evidence of the modified state.
6. Retain the single-intent fast path and do not add an extra model-parsing request per subtask.

## 4. Testing and Performance Boundaries

New tests:

- `tests/test_decision_chain_boundaries.py`: quotations, conditions, polite requests, token boundaries, invalid parameters, dependencies, pending, caching, and bounded evidence.
- `tests/test_decision_chain_execution.py`: runs the real streaming and non-streaming loops with mock providers/tools, plus real clinical prerequisite normalization. It does not merely test a new set of helper functions unrelated to production.

Targeted combined regression: **658 passed, 4 subtests passed, 3 warnings, 10.60 s**.

First full isolated regression: 2069 passed, 2 failed, 8 skipped, 4 subtests passed. The two failures were because the isolated checkout changed the default deployment root of `nnunet_cascade_tumor`, so the existing liver/kidney model resources could not be found; both passed when re-tested in the unmodified authoritative directory. Subsequent re-testing used the existing `BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan` configuration without modifying test assertions or model resources.

See "Delivery Verification" below for the final full and delivery-check results.

Latency verification: In the new execution-loop test, multiple subtasks in one batch still amount to one tool decision plus one result summary, for a total of two provider calls; no intent-recognition calls are added per subtask. This is a call-count proof, not a P95 latency measurement of the actual online model. Context summaries have a size limit; deduplication still occurs when the state is unchanged.

## 5. Broader Capability Acceptance Not Yet Completed

- Real-model testing of arbitrary open-ended instructions, sarcasm, complex cross-sentence conditions, and long-distance anaphora; limited unit tests cannot prove that "all human speech can be understood".
- Automatic dependency continuation after a browser pending-operation receipt, and complete end-to-end behavior during disconnect, reconnect, cancellation, and multi-case switching.
- Clinical normalization still has existing logic that merges a planning flow once by tool category; complex requests with multiple plans and interleaved recomputation comparisons require separate modeling and real-world testing, and cannot be inferred as fully supported from this round's dependency fix.
- A mechanism still exists to stop the current turn and request clarification when key inputs are missing; this round ensures independent tasks can run but does not guarantee that all mixed clarification scenarios produce an optimal final organization.
- The display strategy for intermediate model-stream text and final browser evidence still requires real front-end verification; this round did not mark any unexercised UI issue as fixed.
- Dose, model, planning/guide GPU computation, and clinical effectiveness were not re-verified through this round's software regression.

## 6. Delivery Verification

- After specifying the correct model deployment root in the isolated directory: **2071 passed, 8 skipped, 17 warnings, 4 subtests passed, 52.21 s**.
- First full regression after writing to the official working tree: **2071 passed, 8 skipped, 17 warnings, 4 subtests passed, 54.95 s**.
- After finally supplementing the object bindings in the summary, the full regression revealed that `test_followup_prompt_keeps_only_complete_recent_tool_rounds` does not allow expired call IDs to remain in context. The stale IDs were removed from the summary while the object parameters were kept, without changing the original test assertions. Related execution/budget/boundary/context tests: **60 passed, 3.78 s**.
- **Final official working-tree full acceptance (`python -m pytest tests -q --disable-warnings --maxfail=8`): 2071 passed, 8 skipped, 17 warnings, 4 subtests passed, 55.99 s**. This is the scope of the `tests/` directory and does not mean that all standalone scripts in the repository root or browser/GPU real runs have passed.
- `git diff --check` and Python `compileall` pass. Old reference hashes are not updated, and existing test assertions are not modified to circumvent failures.
- Modified 7 existing source files and added a shared execution-receipt module, 2 test files, and this report. No git commit was made; case data and the separate public service were not changed.
- Original source-file backup: `/tmp/brachy-decision-backup.LAJA4R/original-sources.tgz`. This is a local temporary backup with no guarantee of long-term retention across system cleanups; the git baseline can likewise be used for manual comparison and recovery.
- The current LAN 8080 is still served by the original PID `3792790`, the working directory is this report's baseline directory, and the root page returns HTTP 200. No restart was performed. A healthy root page does not mean the new Python modules have been loaded by the running process.
- Reason: Existing task queries are constrained by user/case scope, and this round has no trustworthy proof that no tasks are running globally; to avoid interrupting planning/guide tasks, switching the running process is deferred until a safe restart window is confirmed. The public deployment was not changed.
- No real-provider online capability evaluation, browser interaction run, or GPU clinical computation was performed; this round's tests do not constitute clinical validation.
- During delivery, another task was found to have added `docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md`; it was neither modified nor cleaned up, and that file is not part of this change.

### Key Code Entry Points

- `agent_runtime/request_parse.py:141`: polite-request grammar; `:230`: original-text quotation ranges; `:715`: protected sentence splitting.
- `agent_runtime/step_execution.py:14`: unified provider argument decoding; `:44`: shared execution receipt; `:56`: batch identity and dependencies; `:102`: completion/pending, state epoch.
- `agent_runtime/llm_runtime.py:977`: bounded same-round evidence; `:2355`, `:3906`: non-streaming/streaming actual batch integration.
