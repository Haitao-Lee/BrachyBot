# BrachyBot External Public Benchmark Selection and Composition Plan

> **2026-10-04 current-inventory notice:** This is a preserved historical design. Current acquisition, eligibility, original-versus-adapted protocol limits and legacy adapter defects are documented in [BENCHMARK_PUBLIC_COLLECTION_AUDIT_2026-10-03.md](BENCHMARK_PUBLIC_COLLECTION_AUDIT_2026-10-03.md) and `benchmarks/external/public_collection/`. Do not use the old inclusion counts or E0 PASS as current model-comparison certification.

**Document version:** 1.1 (v1.1 verification revision: corrected MedCTA acquisition level and commands, added license/activity verification evidence, adjusted the main panel)  
**Date:** 2026-09-29  
**Remote code baseline:** tpx-3090:/home/lht/snap/brachyplan/BrachyBot, HEAD 7aa6d23086072b593beba069f8c2116d01c3c0f3  
**Nature:** Evaluation design report following a read-only review; this round only adds this report and does not modify BrachyBot code, existing benchmark cases, or runtime configuration.  
**Companion main design:** docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md

### v1.1 Revision Summary (item-by-item mapping to user requirement 1 "downloadable and testable" and requirement 2 "no side quests")

| # | Revision | Reason |
|---|---|---|
| M1 | **MedCTA downgraded from main experiment to conditional control**, level R0 → **R0-Gated/R1**, relevance C3 → **C2** | Measured: its README is still an anonymous placeholder (`<ANONYMIZED_REPOSITORY_URL>`), data is distributed via release files, and it depends on **paid Serper + Mathpix API keys**; the tools are generic OCR/retrieval/computation, not clinical workflow tools. Does not satisfy requirement 1 and risks side quests for BrachyBot |
| M2 | **Removed the two MedCTA commands from v1.0** (`huggingface-cli download ... medcta_dataset`, `python run.py configs/eval_medcta_bench.py`) | Inconsistent with the official README workflow; these were speculative commands |
| M3 | Added **§9.4 verification evidence table** (repository existence, License, size, activity, data acquisition) | Requirement 1 needs verifiable download/test evidence |
| M4 | Completed acquisition and licensing facts for ABRA (anonymous submission state + TCIA data), HealthBench (simple-evals no longer updated + LLM judge), MedMemoryBench (HF `Cyan27/MedMemoryBench`, CC-BY-4.0), MedAgentBench (public Docker), and PhysicianBench/HealthAgentBench (Redivis/HF/PhysioNet gating) | Gives the "downloadable" conclusion documentable support |
| M5 | Main external panel converged to three: **ABRA + HealthBench + MedSafetyBench** | Requirement 2: keep only directions directly relevant to the construct and runnable |

---

## 0. Final Conclusion

### 0.1 No public benchmark can replace BrachyBench

As of this verification, no public benchmark simultaneously covers BrachyBot's full pipeline:

> Natural-language requirement → multi-requirement decomposition → intent/action/target binding → tool authorization → CT/segmentation → needle path → seeds → dose/DVH → plan quality → guide → Viewer/Data Tree → screenshot evidence → report → Monitor event loop → recovery/rollback/audit.

Therefore public benchmarks can only serve as external capability anchors and cannot replace BrachyBench. The following brachytherapy-specific content must still be evaluated primarily by BrachyBench:

- Structural and version consistency of CTV/OAR/needle paths/seeds/guides;
- Dose, DVH, OAR metrics, and plan quality;
- Viewer/Data Tree state, object references, camera, and screenshots;
- The evidence loop between screenshot attachments and real objects/real state;
- Events under Monitor, before/after differences, localized advice, reset/retain;
- Authorization, confirmation, dependency ordering, and failure isolation for clinical changes;
- Artifact dependencies of dose → QC/score → report/guide → display.

### 0.2 The three benchmarks recommended for formal inclusion in the paper's external capability panel (v1.1 convergence)

1. **ABRA**: medical imaging Viewer, planning/execution/results, and verifiable evidence; closest to BrachyBot's Viewer/Data Tree/screenshot pipeline.
2. **HealthBench**: clinical answering, communication, risk awareness, and uncertainty; evaluates only final answers and cannot prove that tools actually executed.
3. **MedSafetyBench**: safe requests, dangerous actions, and boundary awareness; must be adapted into a clinical-change authorization suite for BrachyBot and run only in an isolated sandbox.

> **v1.1 change:** v1.0 originally listed **MedCTA** as the fourth main benchmark. After verification, its repository README is still an anonymous placeholder, its data goes through release files, and it depends on paid Serper/Mathpix; its tools are generic OCR/retrieval/computation (not clinical workflow). It **fails both the "downloadable and testable" and "no side quests" requirements**, so it was downgraded to a conditional control (see §3.2).

The results of these three benchmarks must not be combined into a single "overall medical Agent score." They enter different capability panels:

| BrachyBot Capability | External Anchor |
|---|---|
| Viewer, state, evidence screenshots | ABRA |
| Final answers, honesty, risk communication | HealthBench |
| Safety authorization, dangerous-action refusal | MedSafetyBench |

(There is no clean, runnable public anchor for the tool-orchestration/parameter/trajectory direction; it is instead covered by BrachyBench's internal shim metrics. MedCTA is referenced only methodologically; see §3.2 and §5.4.)

### 0.3 Recommended Specialized Extension

- **MedMemoryBench** (R0): for context compression, long-dialogue fact retention, case-switch isolation, misuse of stale planning state, and Chinese-English memory consistency. It is not a brachy benchmark, but it directly covers the long-context and state-memory problems already seen in BrachyBot.

### 0.4 Secondary Controls Rather Than Main Experiments

- **MedCTA** (moved from main experiment in v1.1): generic tool selection/parameters/trajectory, but anonymous submission state + paid API + generic tools, only as a methodological reference;
- **MedAgentBench**: FHIR/EHR stateful tool tasks (public Docker, R0);
- **PhysicianBench**: long-horizon clinical tasks, checkpoint, verifier, pass@k/pass^k (Redivis gated);
- **HealthAgentBench**: terminal Agent, task-level verifier, but some data requires authorization (EHRSHOT/CT-RATE/MIMIC-CXR gated).

They have methodological value but cannot prove that the Viewer, geometry, dose, or guide is correct.

### 0.5 Explicitly Not Included in the Main Experiment

The following items should not be added just to "have more benchmarks":

- Projects with only a paper or incomplete release and no runnable closed loop;
- Projects that require institutional accounts/restricted data to complete;
- Projects that only do EHR, medical administration, patient scheduling, static medical QA, or generic VQA;
- Non-Agent or non-brachy tasks such as generic segmentation or external-beam dose prediction;
- Projects with no interpretable capability mapping to BrachyBot.

---

## 1. Selection Criteria

### 1.1 Five Gates

Every candidate must answer:

1. Is there a public code, task, or data entry point;
2. Is there an official runner, evaluation script, container, or verifier;
3. Does it actually test answers, trajectories, tools, GUI state, artifacts, or safety;
4. Can it be mapped to BrachyBot's capability model;
5. Will it introduce installation, authorization, and interpretation burdens unrelated to the paper's main question.

### 1.2 Acquisition/Reproduction Levels

| Level | Definition | Handling |
|---|---|---|
| **R0** | Code, task/data, and evaluator are public; a minimal smoke can be done without an institutional account; official download/run path exists | Eligible for the main experiment |
| **R0-Gated** | Runner is public, but full data or key resources require authorization such as PhysioNet, Redivis, MIMIC, or HF gated | Secondary control only |
| **R1** | Only part of the code/data is public; lacks a complete verifier, task, or stable run instructions | Not in the main experiment |
| **R2** | Only a paper/survey/method description; no confirmed public runnable closed loop currently | Related work only |

R0 means the public-run threshold is met; it does not mean this report has fully downloaded every project. Formal experiments must pin the commit, data revision, SHA256, environment, logs, and failure reasons.

### 1.3 Relevance Levels

| Level | Definition |
|---|---|
| **C3** | Directly tests Viewer, GUI state, tool calls, evidence, medical Agent trajectories, or safety authorization |
| **C2** | Tests long-horizon workflows, memory, FHIR/stateful execution, or independent verifiers; transferable but a different domain |
| **C1** | Only supports knowledge, generic visual understanding, or localized answering ability |
| **C0** | No necessary intersection with BrachyBot's research construct |

The main external panel selects only R0+C3; specialized tests may choose R0+C2; R0-Gated is not ranked together with R0.

---

## 2. BrachyBot Capability Map

| ID | Capability | What must determine it |
|---|---|---|
| L0 | Medical/dose terminology | Metrics, OAR, CTV, D90, V100, guides, etc. |
| L1 | Requirement understanding and multi-requirement decomposition | Goals, actions, negation, conditions, reference scope |
| L2 | Tool/parameter binding | Tool, object reference, action, parameters, authorization source |
| L3 | Stateful execution | case/session/planning/geometry/version/lease |
| L4 | Evidence and honest answering | Consistency among screenshots, Viewer, Data Tree, structured results, and replies |
| L5 | Viewer/UI | show, hide, color, opacity, camera, slice, drag, restore |
| L6 | brachy computation | segmentation, needle paths, seeds, dose, DVH, OAR, scoring |
| L7 | Artifact contract | dose → QC/score → report/guide → display |
| L8 | Safety authorization | confirmation, prohibition, revocation, failure isolation, and case boundaries |
| L9 | Monitor loop | event → impact → advice → evidence → user choice → recovery |
| L10 | Long context/case isolation | compression, summarization, old/new cases and planning state |
| L11 | Interoperability | DICOM/RT, FHIR, structured plans and reports |
| L12 | Chinese/English communication | language consistency, formatting, explanation granularity, disclaimers |

External benchmarks cover only part of this. No external score may be interpreted as meaning L6, guide geometry, or the clinical plan has been verified.

---

## 3. Formally Included Benchmarks (v1.1: 3 in the main panel + 1 conditional)

## 3.1 ABRA

**Entry points**

- GitHub: https://github.com/Luab/ABRA
- Project page: https://luab.github.io/abra/
- Paper: https://arxiv.org/abs/2605.11224

**Acquisition and Run Assessment (v1.1 measured)**

- Level: **R0\*** (code/task/runner public and smoke-runnable; see asterisk below).
- Verified: repository exists, MIT, about 842KB, updated 2026-07-18; `scripts/`, `configs/`, task generation, and the three-stage scoring pipeline are complete.
- Uses OHIF + Orthanc + Docker + Node.js 20+ + Python 3.11+; the official README provides Phase-0 smoke, task YAML generation, and the full run procedure.
- **Data comes from TCIA collections**: LIDC-IDRI (lung CT), Duke Breast Cancer MRI, NLST New-Lesion LongCT; download scripts are in `data/studies/`; versions and cache hashes must be recorded. **Note:** Some collections (e.g., NLST-derived sets) may carry data use terms that must be confirmed before formal runs; ABRA ships a manifest to verify data versions (`scripts/build_manifest.py`).
- **\* Caution:** The repository is still in an **anonymous submission state** — the README badge is `arXiv XXXX.XXXXX`, the authors are listed as "Placeholder Authors", and the Leaderboard is empty. The code pipeline is runnable, but **before formal citation you must wait for de-anonymization and pin the commit / paper number**.
- Official smoke command (verified item-by-item against the README):
  `python scripts/run_benchmark.py --config configs/tasks/phase0_smoke_test.yaml --agent gpt4o`

**Evaluation Constructs**

- Planning, tool execution, and results in a medical imaging Viewer;
- Object localization and state changes;
- The three stages of planning/execution/results;
- Whether the execution trajectory and final state are consistent;
- Whether the task produces verifiable evidence.

**Transfer to BrachyBot**

| ABRA Construct | BrachyBot Task |
|---|---|
| Viewer state changes | Data Tree show/hide, opacity, color, camera, slice |
| Object localization | Stable references to CTV, guides, seeds, needle paths, OAR |
| Tool trajectory | inspector, screenshot, controller, viewer operations |
| outcome verifier | Attachments, object references, real UI state, post-restore state |
| Planning/Execution separation | Intent decomposition, authorization, tools, result reply |
| Multiple difficulty levels | single-intent, composite, dependent, partial success |

Transfer only the following constructs; do not mechanically copy tasks:

1. Whether the read state belongs only to the current case;
2. Whether UI operations change only the user-requested object;
3. Whether screenshots correspond to real objects;
4. Whether it honestly reports when the target is not visible;
5. Whether temporary camera/display state is restored;
6. Whether dependent tasks are ordered;
7. Whether the final reply references only real results.

**Official Command Form**

~~~bash
git clone https://github.com/Luab/ABRA.git
cd ABRA
pip install -r requirements.txt
./scripts/setup_ohif.sh
python scripts/run_benchmark.py \
  --config configs/tasks/phase0_smoke_test.yaml \
  --agent gpt4o
~~~

The final paper run must follow the README at the pinned commit.

**Handling:** Formal external main experiment; serves as the external anchor for Track F/L5 Viewer and Track H/L4 evidence. Passing ABRA does not mean needle paths, seeds, dose, guides, or clinical safety pass.

---

## 3.2 MedCTA — Downgraded to a Conditional Control in v1.1

**Entry points**

- GitHub: https://github.com/IVUL-KAUST/MedCTA (verified to exist, Apache-2.0, 107 tasks)
- Project page: https://ivul-kaust.github.io/MedCTA/
- Data: https://huggingface.co/datasets/IVUL-KAUST/MedCTA (stated in README)
- Paper: https://arxiv.org/abs/2606.11702 (verified to exist)

**Acquisition and Run Assessment (v1.1 measured revision)**

- Level: **R0-Gated / R1 (not R0)**. Reasons:
  1. The clone command in the repository README is still the placeholder `git clone <ANONYMIZED_REPOSITORY_URL>`, in an anonymous submission state;
  2. The dataset is distributed via "release files", not obtainable with a single `huggingface-cli` command;
  3. Running **requires applying for third-party paid APIs**: Serper (GoogleSearch tool) and Mathpix (MathOCR tool) keys;
  4. Heavy environment stack: OpenCompass + AgentLego + LMDeploy, and it requires manually editing transformers `_supports_sdpa = True`.
- **The two commands in the v1.0 report** (`huggingface-cli download ... --local-dir opencompass/data/medcta_dataset` and `python run.py configs/eval_medcta_bench.py`) **are inconsistent with the official README and have been removed**. The real workflow is the README's four steps: prepare data → start model service → deploy tools → run evaluation.

**Evaluation Constructs**

- Step-level tool fidelity: `InstAcc`, `ToolAcc`, `ArgAcc`, `SummAcc`;
- Clinical reasoning quality: `Facc`, `Cs`, `Scomp`;
- Final result: `Gacc`.

**Tool Set (the decisive limitation, and the main reason for the downgrade)**

- 5 tools: `OCR`, `ImageDescription`, `RegionAttributeDescription`, `GoogleSearch`, `Calculator`.
- They are **generic perception/retrieval/computation tools**: no object references, no authorization, no state, no Viewer/Data Tree. Therefore MedCTA can only verify "generic tool selection/parameters/trajectory" and **cannot verify BrachyBot's clinical tool binding, authorization source, and state contract** — a direction of limited help for the paper's main question.

**Transfer to BrachyBot (methodology only)**

- Borrow its "step-level tool fidelity + final result" metric decomposition (InstAcc/ToolAcc/ArgAcc/SummAcc) to design BrachyBench's internal shim metrics;
- Do not compare tool counts and do not align its 5 generic tools with BrachyBot tools.

**Handling:** **Conditional secondary control (R0-Gated/R1, C2)**; methodological reference only, not in the external main capability panel and not ranked together with R0 benchmarks. If run formally, you must first apply for Serper/Mathpix, pin the commit, and record `requires_credentials: true` in the manifest.

---

## 3.3 HealthBench

**Entry points**

- Official introduction: https://openai.com/index/healthbench/
- Code: https://github.com/openai/simple-evals
- Evaluation script: https://github.com/openai/simple-evals/blob/main/healthbench_eval.py
- Data: https://huggingface.co/datasets/openai/healthbench

**Acquisition and Run Assessment (v1.1 measured)**

- Level: **R0** (code MIT, about 4.6k stars; verified that `healthbench_eval.py` exists).
- Official reference implementation entry point: `openai/simple-evals`; data is loaded by default from `openaipublic.blob.core.windows.net/.../healthbench/2025-05-07-...jsonl`, with the HF mirror `openai/healthbench`.
- **Note:** simple-evals stopped being maintained in 2025-07 (it only continues to host the HealthBench/BrowseComp/SimpleQA reference implementations).
- **Scoring relies on an LLM judge** (the default rubric is decided item-by-item by a grader model); the judge model id/version and cost must be recorded, along with the rubric version and human-scoring settings.
- Suitable for a small-sample smoke followed by stratified formal runs.
- The command module name is indeed `simple-evals.simple_evals` (as stated in the README), verified to be consistent.

**Used Only to Evaluate**

- Whether the answer is direct;
- Whether it honestly expresses uncertainty;
- Whether it distinguishes facts, inferences, unexecuted tools, and insufficient evidence;
- Whether it gives a next step that is useful to the user without overpromising;
- Whether Chinese and English are consistent, clear, and readable.

**Cannot Be Used to Prove**

- Whether tools were actually called;
- Whether the Viewer actually changed;
- Whether guides, reports, dose, or plans were generated;
- Whether the clinical plan is correct.

**Official Command Form**

~~~bash
git clone https://github.com/openai/simple-evals.git
cd simple-evals
pip install -r requirements.txt
python -m simple-evals.simple_evals \
  --eval=healthbench \
  --model=<pinned model id> \
  --examples=20
~~~

**Handling:** Formal main experiment, but it enters only the answering/communication panel, not tool or clinical correctness scores.

---

## 3.4 MedSafetyBench

**Entry points**

- GitHub: https://github.com/AI4LIFE-GROUP/med-safety-bench
- Paper: https://arxiv.org/abs/2403.03744

**Acquisition and Run Assessment (v1.1 measured)**

- Level: **R0** (MIT, about 50 stars, updated 2025-12-04).
- **Datasets are in the repository**: `datasets/train` (900) and `datasets/test` (900), obtainable without external authorization (README verified).
- Content includes potentially harmful requests and explicitly requires "for research use only"; it must not be connected to production cases, real patient data, or instances capable of executing changes.

**Transferable Safety Constructs**

- Whether it identifies dangerous/unauthorized requests;
- Whether it refuses to bypass confirmation, permissions, dependencies, and case boundaries;
- Whether it distinguishes "user inquiry" from "user authorization";
- Whether it stops rather than fabricates when evidence is insufficient;
- Whether it distinguishes explanation, preview, simulation, commit, and persisted changes.

**BrachyBot Adaptation Actions**

- delete/overwrite a guide;
- modify needle paths/seeds;
- recompute dose;
- generate a report;
- export/write a case;
- change the plan;
- restore old geometry;
- bypass user confirmation;
- apply old-case/old-plan facts to a new case.

Each task should annotate: whether authorization is explicit, whether the target is explicit, whether the action is a clinical change, whether it is in a negation/reference/hypothetical/conditional scope, preconditions, and the correct behavior (execute/clarify/refuse/preview/insufficient evidence).

**Handling:** The safety adaptation suite of the formal external main experiment; run only on synthetic state and in an isolated sandbox. Raw harmful requests are not sent directly to the real BrachyBot.

---

## 4. Specialized Inclusion: MedMemoryBench

**Entry points**

- GitHub: https://github.com/AQ-MedAI/MedMemoryBench (verified to exist, about 75 stars, updated 2026-08-07)
- Hugging Face dataset: https://huggingface.co/datasets/Cyan27/MedMemoryBench
- Paper: https://arxiv.org/abs/2605.11814

**Assessment (v1.1 measured)**

- Level: **R0**;
- **License layering:** code Apache-2.0; data CC-BY-4.0; third-party code under `methods/` retains its own license;
- Data is distributed via **Git LFS** (`git lfs install` before cloning), with an additional Hugging Face mirror;
- Command form (README text): `python main.py -m <method> -d medmemorybench` (supports `--dry-run` / `--resume`);
- Suitable for multi-turn, multi-session, case facts, and history retrieval;
- Directly relevant to BrachyBot's context compression, case threading, and stale-state misuse.

**Only Tests the Following Questions**

1. Whether the current case's planning version is retained;
2. Whether the current dose/DVH/guide/report state is retained;
3. Whether key facts are preserved after compression;
4. Whether a new case does not inherit the old case's site, OAR, guide, or conclusions;
5. Whether, when referencing historical messages, it distinguishes originally verified facts from model summaries;
6. Whether the reply after tool execution references the current run;
7. Whether Chinese and English inputs keep the same entity and action.

Do not merge its total score into BrachyBench; do not reward unfounded inference for "remembering more."

**Handling:** Specialized external test, enters Track K/L10, not in the overall ranking.

---

## 5. Conditional Secondary Benchmarks

## 5.1 MedAgentBench

- Code: https://github.com/stanfordmlgroup/MedAgentBench
- Project page: https://stanfordmlgroup.github.io/projects/medagentbench/
- Paper: https://arxiv.org/abs/2501.14654

Its strengths are a FHIR server, stateful EHR tools, and task-level outcome judging, making it a good source for "a tool call does not equal task completion." Its limitation is that the object is EHR/FHIR, not DICOM/RT, Viewer, geometry, or dose.  
**Verified:** public Docker image `jyxsu6/medagentbench:latest` (Docker Hub), no institutional data authorization required → **R0** (MIT, about 333 stars).  
**Conclusion:** R0/C2; optional interoperability and stateful secondary control, not in the main ranking.

## 5.2 PhysicianBench

- Code: https://github.com/HealthRex/PhysicianBench
- Project page: https://healthrex.github.io/PhysicianBench/
- Paper: https://arxiv.org/abs/2605.02240

Its strengths are long-horizon tasks, 100 tasks/670 checkpoints, fresh containers, independent verifiers, and pass@k/pass^k.  
**Verified:** code Apache-2.0, but the EHR data/FHIR Docker image is **gated at Stanford Redivis** (`stanford.redivis.com/datasets/a0ek-0ad8tjsw9`) → **R0-Gated/C2**.  
**Conclusion:** Borrow the checkpoint, resume, verifier, and stability protocols; does not judge brachy artifacts.

## 5.3 HealthAgentBench

- Code: https://github.com/microsoft/HealthAgentBench

Its strengths are a terminal Agent, task-level verifier, and task stratification.  
**Verified:** code MIT, but task categories depend on **gated data**: EHRSHOT (Redivis), CT-RATE (HF OpenRAIL gated), MIMIC-CXR (PhysioNet credentialed) → **R0-Gated/C2**.  
**Conclusion:** Conditional workflow control only.

## 5.4 MedCTA (moved from the main experiment in v1.1)

See §3.2. **R0-Gated/R1, C2**: anonymous submission state + release-file data + paid Serper/Mathpix + generic tools; only a methodological reference for tool-fidelity measurement, not in the main ranking.

---

## 6. Excluded Projects and Reasons

### 6.1 MedFlowBench / MedOpenClaw

The direction is very close to BrachyBot's workflow, but currently no closed-loop package has been confirmed that simultaneously publishes complete code, tasks/data, environment, an independent verifier, smoke test, pinned version, and download instructions.  
**Handling:** High-relevance watchlist; cannot be written up as an already-reproduced public benchmark.

### 6.2 AutoMedBench

- Code: https://github.com/AutoMedBench/AutoMedBench
- Project page: https://automedbench.github.io/
- Paper: https://arxiv.org/abs/2606.01961

The five Plan/Setup/Validate/Inference/Submit stages have methodological value, but the object is a medical AI research/code pipeline, not a clinical Viewer, dose, and guide Agent.  
**Handling:** Not in the main experiment; only borrow the staged validation, isolation, and submission checks.

### 6.3 CHI-Bench, HealthAdminBench, PatientAgentBench

- CHI-Bench: https://github.com/actava-ai/chi-bench
- HealthAdminBench: https://github.com/som-shahlab/health-admin-bench
- PatientAgentBench: https://github.com/amazon-science/PatientAgentBench

They mainly test medical administration, GUI administrative workflows, and patient-side primary care, respectively. Their roles, tools, permissions, and responsibility boundaries differ from BrachyBot's.  
**Handling:** Excluded; retain only their container, GUI verifier, MCP, or pass^k methodological references.

### 6.4 MedAgentAudit, LongMedBench, ClinEnv, MediSkill-Evo, MedRSI

Currently no stable public complete code, tasks, data, and verifier have been confirmed, or the core goal is generic auditing, long-horizon memory, or self-evolution.  
**Handling:** R1/R2 watchlist, not in this round's downloadable main list.

### 6.5 Static Medical QA and Generic Imaging Benchmarks

MedQA, MedMCQA, PubMedQA, MedXpertQA, MedHELM, MMLU-Med, OmniMedVQA, VQA-RAD, SLAKE, PathVQA, CheXbench, MedRAX, DeepTumorVQA, RadAgent, PathAgent, EyeAgent, etc., mainly test knowledge, generic VQA, or other-organ imaging.  
**Handling:** Not in the main experiment; if basic medical QA ability needs to be demonstrated, use it as a separate L0/L1 auxiliary experiment, which cannot replace tool/state/evidence evaluation.

### 6.6 OpenKBP, BraTS, and Generic Segmentation Challenges

OpenKBP is external-beam dose prediction and BraTS etc. are image segmentation, not natural-language Agents.  
**Handling:** Can only be used as BrachyBench fixtures, segmentation oracles, or local dose methodological references.

### 6.7 Same-input rerun, FairMedAgent, DUCX, FHIR-AgentBench

Same-input rerun is a protocol that should be embedded in BrachyBench; fairness data is mostly in other imaging domains; FHIR-AgentBench can serve as an interoperability reference but cannot replace DICOM/RT/Viewer. BrachyBot fairness should build its own stratification by language, case size, site, Viewer layout, object count, and task length.

---

## 7. Boundary Between Public Brachy Data and Agent Benchmarks

| Resource | Can Be Used For | Cannot Prove |
|---|---|---|
| Cervical/prostate/multi-catheter CT | Imaging, structures, needle paths, dose fixtures | That the Agent can understand and execute natural language |
| Segmentation data | CTV/OAR geometry oracle | Tool authorization and Viewer evidence |
| TG-43/MC/TPS references | Dose engine and physics references | That the Agent's tool selection is correct |
| DICOM/RT | Interoperability, import/export | That UI/Data Tree state is consistent |
| Report/guide samples | Artifact format and QA oracle | That the Agent uses the latest version |
| ABRA/MedCTA | Tools, trajectories, evidence, answering methods | brachy geometry and dose correctness |

EMBRACE, the LDR prostate cohort, multi-catheter CT, bladder segmentation, and TG-43/MC references should go into BrachyBench's fixture/reference layer and should not be disguised as a public brachy Agent benchmark.

---

## 8. Recommended Experiment Structure

### E0: Minimal Smoke Gate

| Benchmark | smoke size | pass condition |
|---|---:|---|
| ABRA | 3–10 tasks | Viewer starts, tasks load, at least one outcome |
| HealthBench | 20 samples | Model responses and rubric input are normal |
| MedSafetyBench adapted suite | 20–50 synthetic tasks | All three classes (refuse/clarify/allow) enter the verifier |
| MedMemoryBench | 1 persona + a few sessions | Historical facts and case boundaries are replayable |
| MedCTA (conditional) | 5–10 tasks | Data loading, tool trajectory, and evaluator complete; Serper/Mathpix must be obtained first |

E0 outputs only PASS, FAIL, BLOCKED, LICENSE_REQUIRED, INFRA_FAILED and does not count as a paper result.

### E1: Public External Capability Panel (v1.1)

Pin versions and sample stratified:

- ABRA: Viewer type, difficulty, evidence requirements;
- HealthBench: language, specialty, risk, and multi-turn length;
- MedSafetyBench: unauthorized, quoted commands, negation, conditions, case switching;
- MedMemoryBench: compression, cross-turn, cross-case, version, and language;
- MedCTA (conditional panel, methodology only): tools, implicit steps, parameters, final results.

Because MedCTA is R0-Gated/R1 with generic tools, its panel results serve only as a methodological appendix, are not merged with R0 panels, and are not in the main ranking.

Each panel separately reports success rate, tool-parameter error rate, evidence sufficiency rate, safety violation rate, clarification rate, partial success rate, elapsed time, and retry count, and separates infra_failed from task_failed.

### E2: BrachyBench Main Evaluation

E2 is the paper's main result, using:

- CWS;
- structured artifacts;
- version/dependency graph;
- tool receipts;
- screenshot and attachment fences;
- dose/DVH/geometry oracles;
- guide QA;
- Monitor events and recovery;
- same-input reruns;
- the safety triple gate;
- report/viewer/data-tree alignment.

The results of the external main panel (ABRA / HealthBench / MedSafetyBench) and the conditional anchors (MedCTA / MedMemoryBench, etc.) are placed only in the External Capability Anchors table and are not merged into BrachyBench's main endpoints.

---

## 9. Acquisition, Version Pinning, and Isolation Specifications

### 9.1 acquisition manifest

Each benchmark must save:

~~~yaml
benchmark: ABRA
source_url: https://github.com/Luab/ABRA
source_commit: <pinned-commit>
dataset_url: <official-data-url>
dataset_revision: <pinned-revision>
license: <recorded-license>
download_command: <exact-command>
smoke_command: <exact-command>
evaluator_command: <exact-command>
requires_credentials: false
requires_institutional_data: false
network_required: true
expected_runtime_class: medium
expected_disk_class: large
status: R0
verified_at: 2026-09-29
verified_by: <machine-and-run-id>
~~~

Also save the environment, models/APIs, task-list hash, evaluator version, timestamps, artifact directories, and failure classification.

### 9.2 Evidence Boundaries of This Verification

This report has completed:

- Cross-checking of official repositories/project pages/paper entry points;
- Verification of the acquisition/run paths in public repos and official READMEs;
- Verification of the remote HEAD, nonexistence of target files, and the status of existing design documents;
- Classification into R0/R0-Gated/R1/R2 and C3/C2/C1/C0.

This report does not claim to have completed:

- full data downloads for each project;
- full runs of each project;
- obtaining formal scores with BrachyBot;
- authorization for restricted data;
- clinical performance conclusions.

Because external data may be very large or require authorization, formal experiments must first run E0 and write the real status back to the manifest. Download/runner failures should be marked INFRA_FAILED or LICENSE_REQUIRED and must not be recorded as a model score of zero.

### 9.3 Environment Isolation

External benchmarks must not share the following with BrachyBot production/LAN services:

- .runtime;
- account databases;
- case directories;
- planning data;
- the 8080 service;
- GPU leases/locks;
- real clinical artifacts.

Each benchmark uses an independent environment, cache, output directory, and logs.

### 9.4 v1.1 Verification Evidence Table (2026-09-29)

**Verification method:** GitHub repositories were confirmed to exist via `api.github.com/repos/<owner>/<repo>` returning HTTP 200, and License/size/stars/most recent push were read; papers were confirmed via `arxiv.org/abs/<id>` returning 200; READMEs were fetched via jsdelivr and compared item-by-item with the report's commands. **Hugging Face pages are network-restricted on this machine (timeout); HF datasets are recorded only as referenced by the official README and must be re-verified on a reachable network before formal use.**

| Project | Repository | License | Size/Stars | Most recent push | Data acquisition | Verdict |
|---|---|---:|---:|---|---|---|
| ABRA | ✔ 200 | MIT | 842KB / 6 | 2026-07-18 | TCIA public (LIDC-IDRI / Duke Breast MRI / NLST-LongCT) | R0\* (README anonymous state) |
| MedCTA | ✔ 200 | Apache-2.0 | 12.1MB / 8 | 2026-06-11 | release files + **paid Serper/Mathpix** | **R0-Gated/R1** |
| HealthBench (simple-evals) | ✔ 200 | MIT | 110KB / 4.6k | 2026-04-22 | openaipublic blob / HF `openai/healthbench` | R0 |
| MedSafetyBench | ✔ 200 | MIT | 3.2MB / 50 | 2025-12-04 | **in-repo** datasets/{train,test} | R0 |
| MedMemoryBench | ✔ 200 | Apache-2.0(code)/CC-BY-4.0(data) | 23MB / 75 | 2026-08-07 | Git LFS / HF `Cyan27/MedMemoryBench` | R0 |
| MedAgentBench | ✔ 200 | MIT | 1.1MB / 333 | 2025-11-21 | public Docker `jyxsu6/medagentbench:latest` | R0 |
| PhysicianBench | ✔ 200 | Apache-2.0 | 11.2MB / 59 | 2026-08-13 | Redivis gated | R0-Gated |
| HealthAgentBench | ✔ 200 | MIT | 5.6MB / 54 | 2026-09-25 | EHRSHOT/CT-RATE/MIMIC-CXR gated | R0-Gated |
| AutoMedBench | ✔ 200 | MIT | 8.1MB / 62 | 2026-07-09 | Medical AI research pipeline | Excluded |
| CHI-Bench | ✔ 200 | Apache-2.0 | 3.4MB / 64 | 2026-09-24 | Medical administration | Excluded |
| PatientAgentBench | ✔ 200 | NOASSERTION | 1.0MB / 30 | 2026-09-19 | Patient-side | Excluded |
| health-admin-bench | ✔ 200 | Apache-2.0 | 30.9MB / 30 | 2026-09-29 | Medical administration | Excluded |

**Two conclusions follow:**
1. All listed links really exist (no fabricated entries);
2. But "the repository exists" ≠ "one-click downloadable and testable" — only ABRA, HealthBench, MedSafetyBench, MedMemoryBench, and MedAgentBench satisfy R0; MedCTA and PhysicianBench/HealthAgentBench are gated by paid APIs and institutional data respectively and must be re-classified per v1.1 (see §3.2 and §5).

---

## 10. Metrics and Result Interpretation

### 10.1 Capability Profiles, No Meaningless Overall Score

| Panel | Main Metrics | External Anchor | Primary Source |
|---|---|---|---|
| P1 Answering/Communication | rubric, honesty, uncertainty | HealthBench | BrachyBench C |
| P2 Tool Orchestration | tool/action/arg/trajectory accuracy | (no clean external anchor; MedCTA is methodology-only, conditional) | BrachyBench B |
| P3 Viewer State | state, object binding, restore | ABRA | BrachyBench F |
| P4 Evidence Chain | receipt/evidence alignment | ABRA (MedCTA methodology-only) | BrachyBench H |
| P5 Safety | unsafe action rate, authorization accuracy | MedSafetyBench | BrachyBench D |
| P6 Memory | fact retention, case isolation | MedMemoryBench | BrachyBench K |
| P7 brachy Core | dose/geometry/guide/report consistency | no public substitute | BrachyBench A/G/J/L |
| P8 Monitor | event impact, localized advice, rollback | no public substitute | BrachyBench I |
| P9 Efficiency | latency, tool count, retry, GPU time | recorded individually | BrachyBench G |

### 10.2 A Tool Call Does Not Equal Completion

Must distinguish:

- parse success;
- planning success;
- tool call success;
- tool return success;
- world state changed correctly;
- artifact version correct;
- evidence verifiable;
- final answer accurate.

For example: calling ui_screenshot does not mean the attachment was returned; returning report.autofill does not mean the report used the latest dose; returning surgical_guide does not mean the guide is manufacturable; reading OAR volume does not mean knowing OAR dose; writing "complete" does not mean the clinical change is complete.

### 10.3 Partial Success

In composite tasks, an independent subtask failure must not erase successful items, nor should the whole task be written as a success. Each subtask must record at least:

- task_id, target_ref, action, authorization, dependency;
- tool calls;
- before/after state;
- evidence;
- final status;
- user-visible explanation.

Recommended statuses:

- COMPLETED;
- PARTIAL;
- NEEDS_CLARIFICATION;
- BLOCKED_BY_DEPENDENCY;
- REFUSED_FOR_SAFETY;
- FAILED_TOOL;
- FAILED_VERIFICATION;
- INFRA_FAILED.

---

## 11. Cross-Comparison, Contamination, and Repeated Runs

### 11.1 Do Not Directly Merge Scores from Different Benchmarks

Different tasks, data, tool permissions, result spaces, and human rubrics cannot be directly averaged. The paper reports "capability panels" and "external anchors," not a seemingly precise overall score with no measurement meaning.

### 11.2 Fixed Conditions

When comparing with other Agents/AI, the following must be fixed:

- user request;
- benchmark/task version;
- system prompt;
- tool schema and return format;
- temperature/top-p/reasoning effort;
- maximum turns and timeout;
- network/API permissions;
- seed;
- retries and human confirmation;
- historical context.

Report separately capability-comparable and interface-comparable differences caused by different tools.

### 11.3 Anti-Contamination

- Do not hard-code public test examples, answers, trajectories, and keywords into BrachyBot shortcut routing;
- Public examples are used only for development smoke;
- The paper uses a sealed or newly generated BrachyBench;
- External results and internal debug output are archived separately.

### 11.4 Same-input rerun

For high-risk tool Agents, a single pass is insufficient to demonstrate stability. At minimum, repeatedly compare:

- subtask decomposition;
- tool set;
- parameters;
- state changes;
- evidence;
- final reply;
- safety conclusions.

Same-input rerun is an internal BrachyBench protocol and is not disguised as another domain benchmark.

---

## 12. Recommended Combination for the Paper's Formal Experiments

### 12.1 Limited Resources (v1.1)

Use:

1. ABRA: Viewer/evidence;
2. HealthBench: answering and honesty;
3. MedSafetyBench: safety;
4. BrachyBench: the complete brachytherapy main evaluation.

This already covers external general capabilities (Viewer state, communication honesty, safety authorization) and the internal domain core. The tool-orchestration direction is covered by BrachyBench's internal shim metrics (no clean external anchor).

### 12.2 Sufficient Resources (v1.1)

Add on top of the above:

5. MedMemoryBench: long context/case isolation (R0, recommended as priority);
6. MedAgentBench: FHIR/state interoperability (R0);
7. MedCTA: generic tool-fidelity methodological reference (R0-Gated/R1, requires paid API);
8. PhysicianBench / HealthAgentBench: long-horizon checkpoint/verifier (R0-Gated).

5–8 do not change BrachyBench's main endpoints and are not combined with the main benchmarks into an overall score; R0-Gated items are not ranked together with R0 items.

### 12.3 Not Recommended

Do not simultaneously add large amounts of static QA, chest X-ray/pathology VQA, EHR, administration, generic segmentation, external-beam dose, and paper projects without runners. This only adds installation/authorization/statistics burden and cannot answer whether BrachyBot reliably executes and explains the brachytherapy workflow.

---

## 13. Suggested Paper Wording

May use:

> To the best of our search, no publicly runnable benchmark evaluates the complete natural-language-to-brachytherapy-planning loop, including target/OAR structures, needle and seed geometry, dose/DVH, surgical-guide generation, viewer state, screenshot evidence, report versioning, and monitor-time recovery. We therefore use ABRA, HealthBench, and an adapted MedSafetyBench suite as external capability anchors (with MedCTA and MedMemoryBench as conditional method anchors), while evaluating the domain-specific planning and evidence contract with our own BrachyBench.

Corresponding Chinese:

> 公开 benchmark 可以验证 BrachyBot 的通用 Agent 能力、医学沟通、安全边界和影像 Viewer 交互，但不能替代近距离治疗领域的剂量、几何、导板和状态契约评测。因此公开 benchmark 作为外部能力锚点，BrachyBench 作为领域主评测。

Do not write:

- prove clinical safety via HealthBench;
- prove guide generation is correct via ABRA;
- prove dose planning is correct via MedCTA;
- prove that real cases cannot go wrong via MedSafetyBench;
- that a public benchmark's overall score represents the general level of medical intelligence.

---

## 14. Risks and Re-inclusion Conditions

### 14.1 Version and Data Drift

Public repositories may change the default branch, data revision, model interface, or dependencies. Formal runs must pin the commit and must not use latest.

### 14.2 Data Authorization

Public code does not mean the data is unconditionally public. For PhysioNet, Redivis, MIMIC, CT-RATE, or other gated assets:

- record the application status;
- mark unauthorized ones as LICENSE_REQUIRED;
- do not record a non-run as a model failure;
- do not perform unequal ranking against R0 benchmarks.

### 14.3 Resource Cost

ABRA, MedCTA, and multi-model/long-context runs may consume substantial disk, GPU, containers, and network. Do E0 first, then small-scale E1, then full-scale; external environments must not write to the 8080 BrachyBot runtime.

### 14.4 Re-inclusion Conditions

Currently excluded projects re-enter R0 review only after they simultaneously provide code, tasks/data, a verifier, installation instructions, a pinned release/commit, smoke, and license/data terms.

---

## 15. Suggested External Directory Structure

Not required for this round, but the formal experiment package should be isolated:

~~~text
benchmarks/
  external/
    manifest.yaml
    abra/
      README.md
      source_commit.txt
      dataset_revision.txt
      smoke.log
      results/
    medcta/
      README.md
      source_commit.txt
      dataset_revision.txt
      smoke.log
      results/
    healthbench/
      README.md
      source_commit.txt
      dataset_revision.txt
      smoke.log
      results/
    med_safety_bench_adapted/
      README.md
      source_commit.txt
      task_manifest.json
      smoke.log
      results/
    med_memory_bench/
      README.md
      source_commit.txt
      dataset_revision.txt
      smoke.log
      results/
  brachybench/
    ...
~~~

External result directories must not write into BrachyBot's session, case, runtime, or report directories.

---

## 16. Final Selection Table

### 16.1 Included in the Main Experiment (v1.1)

| Benchmark | Level | Relevance | Acquisition/Test | Test Direction |
|---|---|---|---|---|
| ABRA | R0\* | C3 | Public code/tasks/runner; data from TCIA | Viewer, state, object localization, evidence |
| HealthBench | R0 | C3 | Public code/data/script (needs LLM judge) | answering, honesty, uncertainty, communication |
| MedSafetyBench (Brachy adaptation) | R0 | C3 | Datasets in-repo, isolated adaptation | authorization, refusal, dangerous boundaries |

(\* The ABRA README is still in an anonymous submission state; before formal citation you must pin the commit/paper number.)

### 16.2 Specialized or Secondary Controls (v1.1)

| Benchmark | Level | Relevance | Handling |
|---|---|---|---|
| MedMemoryBench | R0 | C2 | Long-context/case-isolation specialized test (recommended as priority) |
| MedAgentBench | R0 | C2 | FHIR/stateful tool secondary control (public Docker) |
| MedCTA | **R0-Gated/R1** | **C2** | Generic tool-fidelity methodological reference; anonymous state + paid Serper/Mathpix, not in the main ranking |
| PhysicianBench | R0-Gated | C2 | checkpoint/verifier methodological reference (Redivis gated) |
| HealthAgentBench | R0-Gated | C2 | terminal/verifier secondary control (EHRSHOT/CT-RATE/MIMIC gated) |

### 16.3 Not in the Main Experiment

| Category | Representative Projects | Reason |
|---|---|---|
| No complete closed loop | MedFlowBench/MedOpenClaw, some new papers | Cannot confirm public downloadability, reproducibility, and verifier |
| Medical research pipeline | AutoMedBench | Not a clinical Viewer/planning Agent |
| Medical administration | CHI-Bench, HealthAdminBench | Not a core workflow |
| Patient-side primary care | PatientAgentBench | Different roles, tools, permissions |
| EHR/FHIR | MedAgentBench, PhysicianBench, HealthAgentBench | Secondary control only |
| Static medical QA | MedQA, MedMCQA, PubMedQA, MedHELM | Cannot test tools/state/evidence/plans |
| Generic imaging VQA | VQA-RAD, SLAKE, PathVQA, MedRAX | Cannot test the brachy pipeline |
| External-beam/generic segmentation | OpenKBP, BraTS | fixture/local capability, not an Agent |
| Protocol/method | Same-input rerun, fairness protocol | Embedded in BrachyBench, not scored independently |

---

## 17. Conclusion

The most reasonable approach is not to download as many medical benchmarks as possible, but to establish a clearly bounded two-layer evaluation:

### External Layer (v1.1)

- ABRA: imaging Viewer, state, and evidence;
- HealthBench: answer quality, honesty, and communication;
- MedSafetyBench: safety authorization and dangerous-request handling;
- MedMemoryBench: long-context and case-isolation specialized test;
- (Conditional) MedCTA: generic tool-fidelity methodological reference, requires paid API, not in the main ranking;
- (Conditional) MedAgentBench / PhysicianBench / HealthAgentBench: stateful/long-horizon verifier secondary controls.

### Internal Main Layer

- BrachyBench: geometry, dose, DVH, plan, guide, report, Viewer, screenshots, Monitor, recovery, audit, and state contracts.

Final principle:

> **Public benchmarks are responsible for proving whether BrachyBot's general Agent capabilities reach a comparable level; BrachyBench is responsible for proving whether it truly understands and reliably executes the brachytherapy workflow. The two are complementary but cannot substitute for each other.**

---

## 18. Reference Entry Points

- ABRA GitHub: https://github.com/Luab/ABRA
- ABRA project: https://luab.github.io/abra/
- ABRA paper: https://arxiv.org/abs/2605.11224
- MedCTA GitHub: https://github.com/IVUL-KAUST/MedCTA (v1.1 verification: README still contains `<ANONYMIZED_REPOSITORY_URL>`; data goes through release files; requires paid Serper/Mathpix)
- MedCTA project: https://ivul-kaust.github.io/MedCTA/
- MedCTA dataset: https://huggingface.co/datasets/IVUL-KAUST/MedCTA
- MedCTA paper: https://arxiv.org/abs/2606.11702
- HealthBench official page: https://openai.com/index/healthbench/
- simple-evals: https://github.com/openai/simple-evals
- HealthBench dataset: https://huggingface.co/datasets/openai/healthbench
- MedSafetyBench: https://github.com/AI4LIFE-GROUP/med-safety-bench
- MedSafetyBench paper: https://arxiv.org/abs/2403.03744
- MedMemoryBench: https://github.com/AQ-MedAI/MedMemoryBench
- MedMemoryBench dataset: https://huggingface.co/datasets/Cyan27/MedMemoryBench
- MedMemoryBench paper: https://arxiv.org/abs/2605.11814
- MedAgentBench: https://github.com/stanfordmlgroup/MedAgentBench
- PhysicianBench: https://github.com/HealthRex/PhysicianBench
- HealthAgentBench: https://github.com/microsoft/HealthAgentBench
- AutoMedBench: https://github.com/AutoMedBench/AutoMedBench
- CHI-Bench: https://github.com/actava-ai/chi-bench
- PatientAgentBench: https://github.com/amazon-science/PatientAgentBench
- HealthAdminBench: https://github.com/som-shahlab/health-admin-bench
- Same-input rerun protocol: https://arxiv.org/abs/2609.13582
- Awesome Medical Agents index: https://github.com/zhcz328/Awesome-Medical-Agents


---

## Appendix Z · 2026-10-01 Revision (include only benchmarks BrachyBot can participate in)

On 2026-10-01 the user tightened the inclusion criteria: **include only public benchmarks that BrachyBot can participate in as a SUT and that are suitable for evaluating it**. The 8-item list of this document v1.1 was revised accordingly and implemented via `benchmarks/external/manifest.yaml`. See DESIGN §25.2.5 for the synchronized main design.

### Z.1 Changes

* **Retained (4)**: EXT-1 ABRA, EXT-2 HealthBench, EXT-3 MedSafetyBench-Brachy, EXT-4 MedMemoryBench.
* **Added (7)**: EXT-9 LongMemEval (P6 memory), EXT-10 MedHallu (P1 hallucination),
  EXT-11 MedCalc-Bench (P2 calculation), EXT-12 AgentClinic (P1 consultation), EXT-13 AMEGA (P5 guidelines),
  EXT-14 MedPhysBench (P4/P5 medical physics: **includes brachytherapy**, TG-263, dose, safety escalation),
  EXT-15 MedicalAgentsBench (P1 medical reasoning MCQ).
* **Excluded (4)**: EXT-5 MedAgentBench, EXT-6 MedCTA, EXT-7 PhysicianBench,
  EXT-8 HealthAgentBench — BrachyBot has no FHIR/EHR/HL7/terminal capability (source grep = 0),
  and some require paid APIs/gated data. Records are in `benchmarks/external/excluded/`.

### Z.2 Inclusion Evidence (item by item)

| # | Repository | commit | Data | License | E0 |
|---|---|---|---|---|---|
| EXT-9 | xiaowu0162/LongMemEval | 9e0b455f | HF longmemeval-cleaned (oracle+s) | MIT | BLOCKED (judge) |
| EXT-10 | MedHallu/MedHallu | 3c49c8ba | HF UTAustin-AIHealth/MedHallu | MIT | PASS |
| EXT-11 | ncbi-nlp/MedCalc-Bench | 20b10f9d | HF ncbi/MedCalc-Bench test | CC-BY-SA-4.0 | PASS |
| EXT-12 | SamuelSchmidgall/AgentClinic | b6570ede | in-repo jsonl | MIT | BLOCKED (judge) |
| EXT-13 | DATEXIS/AMEGA-benchmark | 16fd048a | in-repo csv | Apache-2.0 | PASS |
| EXT-14 | udiram/MedPhysBench | bde8dc6d | in-repo tasks/public (97) | MIT / tasks CC0 | PASS |
| EXT-15 | gersteinlab/MedicalAgentsBench | fcb52927 | HF super-dainiu/MedicalAgentsBench | MIT | PASS |

### Z.3 Candidates Not Included in the Secondary Search (quality first)

* 3MDBench (univanxx/3mdbench): requires vision (LVLM doctor); BrachyBot is not multimodal.
* mediQ (stellalisy/mediQ): the official `src/evaluate.py` is a placeholder implementation (random scores); no reliable upstream scoring.
* MedAgentGym / MedAgents: no open-source license.
* Generic Agent/function-calling benchmarks (BFCL, τ-bench, etc.): non-medical domain; moreover DESIGN §0.2 has decided that tool
  orchestration is covered by BrachyBench's internal shim metrics, without external anchors.
* MTBBench (bunnelab/mtbbench): multimodal (pathology/genomics/imaging) + depends on HANCOCK/MSK-CHORD
  external data; BrachyBot cannot participate.
* CliBench (CliBench/CliBench): data built from MIMIC-IV via scripts (PhysioNet gated).
* ClinicalAgentBench (BlueZeros): eICU/EHR-SQL + VQA; BrachyBot has no SQL/EHR/vision capability.
* MedAgentBoard / MedAgentSim / MedAgentGym / MedAgents: no open-source license.
* mediQ: the official evaluator is a placeholder implementation.
* 3MDBench: requires vision (LVLM doctor).
* Static medical QA singletons (MedMCQA/PubMedQA, etc.): already incorporated in aggregate via EXT-15 MedicalAgentsBench,
  and not counted separately.
