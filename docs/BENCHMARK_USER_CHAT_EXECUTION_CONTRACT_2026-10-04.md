# BrachyBot Benchmark Execution Contract: Use the Real User Chat Entry Point

Effective date: 2026-10-04. This contract implements the requirement that benchmark tasks be tested as if a user had entered each request in the chat dialog. It applies to the in-house PRV suite and public EXT evaluations. This change establishes the entry-point policy and offline regression checks; it does not launch model evaluations.

## 1. Evaluate the complete product, not a model answering on its behalf

The formal experiment path is:

`Prepare an isolated test case/session → enter the task in page #chatInput → activate #chatSendBtn → use the page's own routing, session, and authentication → parse and authorize the request → execute tools → complete browser-side rendering, screenshots, reports, and other post-processing → expose the final user-visible response → collect evidence and score independently`

Use the actual input field and Send button. Do not directly call `sendChat()`, `chat_with_trace()`, an LLM provider, an internal tool, or a manually constructed `/api/chat` request. This preserves the page's own recognition of control commands such as Monitor, continue-task, and context compression; do not force these commands through the LLM for evaluation convenience.

A regular user POST to `/api/chat` may be collected as **observational evidence**, but calling that API alone does not prove that the browser completed a screenshot, saved a report, or rendered the response. A server tool being dispatched, SSE reaching EOF, or the first response segment appearing does not establish completion of the user task.

## 2. Input boundaries

- Submit only the current task's public user request and legitimate supporting materials. Do not expose labels, reference answers, oracles, rubrics, expected tools, or future questions to BrachyBot.
- Send multi-turn tasks sequentially in one isolated session. Turn N+1 may use only the real responses to turns 1 through N. Never replace conversation history with reference answers or preload the full future dialogue.
- Images must enter the product through an actually supported user-upload interaction. Load CT, cases, plans, and corpora through a verified environment-preparation workflow. A filename does not prove that an image was viewed; do not substitute plain text for missing imaging data.
- System, assistant, and tool messages do not grant user authorization. Malicious content in a public prompt-injection benchmark must appear through a genuine low-trust retrieval or tool-result source; do not convert it into an ordinary user command and present that as the original attack protocol.
- Manual button events, case switches, and background events may be simulated by an independent environment driver, but it must not perform an action that the task expects BrachyBot to decide and execute. If the required driver is unavailable, mark the task BLOCKED.

## 3. Completion, failure, and efficiency

For ordinary text chat, record the actual user-facing network request, user echo, request/user-message/assistant-message IDs, owning session, every turn's raw and rendered final text, attachments, and tool trace.

Declare completion only when all of the following hold: the session has not changed; the user echo matches the task; there is exactly one final response belonging to the correct request; the response and attachments are mounted; the trace is no longer pending; and the ordinary stream, hidden visual follow-up, pending screenshot response, stop barrier, and other post-processing have all settled. Confirm this across at least two observation times so a transient idle moment in one event loop is not mistaken for completion.

An independent collector must also verify server task terminal state, UI-action receipts, report persistence, planning version, geometry revision, artifact hashes, and restoration of temporary state. Browser-entry evidence **does not replace** task-level checks; the presence of natural-language text is not proof of a medical or geometry task passing.

For timeouts, wrong-case execution, duplicate final responses, or inconsistent state, record the actual failure or insufficient evidence. Do not fabricate completion or automatically resend the task. Include browser-side post-processing time in the budget. Report provider latency, tool latency, and end-to-end user time rather than only LLM time. Isolate test accounts, runtime directories, and cases from in-use cases and the public-release service.

## 4. Implementation scope

- `benchmarks/execution_policy.json`: shared policy for future formal PRV and EXT experiments.
- `benchmarks/user_chat_contract.py`: contracts for input identity, isolation, turn sequencing, and completion evidence. EXT's `UserChatHandle` may bind only to a real browser session.
- `brachybench/tools/adapters/user_chat.py`: performs a real Playwright `fill` and `click` on an evaluator-prepared page; read-only collection of DOM/page state and network identity. Importing it does not create a browser, start a server, or call a model.
- `run_task.py`: the formal entry point rejects arbitrary Python/direct-agent adapters and blocks before submission if the independent collector or answer/completion checkers are missing. Formal results require harness-owned user-chat execution evidence.
- `live_smoke.py`: no longer creates a `BrachyAgent` merely because a provider key exists in the environment. Without an isolated browser and independent evaluation configuration, it reports BLOCKED.
- `external/adapter_base.py`: rejects arbitrary model callbacks by default. Offline E0/regression runs must explicitly set `evaluation_mode=component_self_test` and cannot count as formal results.

This is a trusted-harness execution contract, **not an OS sandbox for malicious Python adapters**. A real experiment must still isolate private gold data from the SUT's filesystem, permissions, and processes; the presence of a field is not proof of tamper resistance.

## 5. Supported scope and explicitly unfinished work

The default browser driver supports ordinary **text** chat in an independently prepared case/session and sequential submission of plain-text multi-turn tasks. It requires an evaluator-owned browser-session factory, fixture driver when a task has preconditions, independent collector, response checker, and completion checker.

The default driver will not silently downgrade the following cases; they are explicitly rejected or not yet certified:

1. Image/case-upload tasks: require a real upload-UI driver and evidence that the content was ingested.
2. Front-end control tasks such as Monitor, context compression, and continue: the input must still go through the dialog, but these tasks must not be required to produce an ordinary `/api/chat` final response. The generic text driver cannot determine their completion; an independent terminal-state oracle is needed before they can be enabled. Current status: BLOCKED.
3. Protocols with UI, background, or other non-user events: require an independent event scheduler.
4. Fixed retrieval corpora, external-tool simulations, and injected tool-return content: require native environment integration; otherwise retain the assets but do not run them formally.
5. Real environment factory, login, case import, and independent artifact collection: this change did not create test accounts for the clinical service, install a browser, or provide a fake fixture installer. Do not claim that all historical tasks can already run through the live page.

These are experimental prerequisites, not reasons to delete tasks. Reports must show eligible, blocked, and excluded counts with reasons to avoid selection bias from presenting only tasks that happen to run.

## 6. Executing and naming public benchmarks

Keep all assets intact and do not weaken original scorers to accommodate the required entry point. Per-benchmark gates are listed in `external/public_collection/user_chat_eligibility.json`.

| Category | Required handling |
|---|---|
| Medical text QA, error correction, calculation, safety, and hallucination tasks | Submit the original public prompt/material through the real page as the current user turn using a validated template. Separately certify answer-format compatibility, scoring, and budget against the original protocol. |
| CMB-Clin, clinical memory, and long-context tasks | Send turns sequentially; do not use teacher forcing. Product conversation or upload protocols for memory initialization and document composition must be traceable. |
| Medical image tasks | Run only after real upload is supported and verified; report text-only and multimodal results separately. |
| R2MED / NFCorpus / SciFact retrieval | The product must access the same frozen public corpus and obtain ranked IDs through its actual retrieval tools. Directly calling a retriever does not constitute a BrachyBot user task. |
| When2Call / BFCL | External tools and original likelihood/AST protocols are not automatically satisfied by ordinary chat. Retain the assets and methods, but mark native product runs BLOCKED. If adapted into explanation/JSON answering, give the adaptation a distinct `user-chat-adapted` name and do not attach original leaderboard scores. |
| InjecAgent / ABRA / AgentClinic | Mark BLOCKED when the external executor, patient simulator, or OHIF/Orthanc environment is unavailable. Do not replace full interaction with keywords, final text, or a synthetic scenario. |

Earlier common-harness/raw-model recommendations in other documents are historical methodological context only; they are no longer formal BrachyBot test entry points. A shared entry point does not imply protocol equivalence. Report adapted tasks in a separate table from original benchmark names and scores; do not combine them into one total.

For cross-system comparison, submit the same task and materials through each product's public user-facing entry point and define the capability boundary shared by all systems. A separate experiment on underlying models is a model study, not a BrachyBot agent evaluation under this policy. A paid model provider's native API may serve as that provider's public user entry point, but its answer cannot substitute for BrachyBot execution. Disclose differences in evidence, UI capabilities, and latency measurement between browser-based products and APIs.

## 7. Example run configuration (not executed for this change)

```bash
cd benchmarks/brachybench
export BRACHYBENCH_BROWSER_SESSION_FACTORY=my_eval.browser:prepared_session
export BRACHYBENCH_BROWSER_FIXTURE_DRIVER=my_eval.fixtures:prepare_isolated_case
python tools/live_smoke.py --task tasks/D1-SA-007.json \
  --evaluator-config /private/evaluator.json \
  --collector my_eval.evidence:collect \
  --response-checker my_eval.grade:answer \
  --completion-checker my_eval.grade:completion
```

`prepared_session(scope)` must return a `BrowserChatSession` bound to an isolated page. `prepare_isolated_case(task, initial_state)` is a private evaluator environment driver, not a SUT answering interface. `collect(session, context=...)` reads the execution's actual state and artifacts and must not rewrite the final response.

Legacy replay and direct-agent regression tests may still run to validate parsing/scoring components, but they must be labeled `component_self_test`. Their pass counts, expected-positive replays, and construction checks are not experimental performance results.

## 8. Validation for this change

Only offline regression and syntax/diff checks were performed. No task was submitted through an actual page; no provider, judge, or GPU was called; no clinical plan was generated; and no running service was restarted. See `benchmarks/user_chat_validation_2026-10-04.json` for the recorded validation results. Existing sealed manifests are not automatically renewed; after a runner change, re-audit and freeze the protocol before a formal experiment.

The 37 new user-chat contract tests passed. The combined in-house benchmark and public-collection test run reported **24,293 passed / 2 skipped / 0 failed** in 161.55 seconds. Both skips were due to `pypdf` being unavailable in the isolated validation environment. These are not model results and do not certify the real browser, upload, or control-task environments.
