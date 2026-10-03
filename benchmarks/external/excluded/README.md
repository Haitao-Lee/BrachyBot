# EXT Track · Non-included candidates (BrachyBot cannot participate)

A benchmark is included under `external/EXT-*` only if BrachyBot **can participate as the SUT** and the
benchmark **is suitable for evaluating BrachyBot**. The following candidates are therefore excluded; their
acquisition manifests are kept here for audit.

| # | Benchmark | R/C | Exclusion rationale (why BrachyBot cannot participate) |
|---|---|---|---|
| EXT-5 | MedAgentBench | R0/C2 | The task is **FHIR tool calling** (HAPI FHIR server); BrachyBot's source has **zero references** to `fhir/ehr/hl7`, so it has no FHIR capability. Also, the upstream public repo lacks the grader `refsol.py`. |
| EXT-6 | MedCTA | R0-Gated/C2 | The tools are **generic OCR/retrieval/calculation** (not a clinical workflow), depending on **paid Serper + Mathpix**; the task data is not public. BrachyBot cannot participate in its toolchain, nor can it validate the clinical binding. |
| EXT-7 | PhysicianBench | R0-Gated/C2 | Long-horizon EHR tasks based on **FHIR + MiniAgent**; BrachyBot has no FHIR/EHR capability, and the data is **Redivis**-gated. |
| EXT-8 | HealthAgentBench | R0-Gated/C2 | **terminal Agent + EHRSHOT/CT-RATE/MIMIC-CXR** gated data + CheXprompt judge; BrachyBot has no EHR/terminal capability. |

Criteria (evidence of BrachyBot's capabilities):

* BrachyBot is a **brachytherapy Viewer/planning** agent, with tool domains such as
  `ui_* / planning_* / dose_* / case_* / session_* / report_* / guide_*`;
* repo-wide `grep -iE "fhir|ehr|hl7|redivis|mimic-cxr"` = **0**;
* therefore only the four external benchmark categories "answering/communication, safety, memory,
  imaging Viewer" are suitable for its participation
  → retain **EXT-1 ABRA / EXT-2 HealthBench / EXT-3 MedSafetyBench / EXT-4 MedMemoryBench**.

Inclusion criteria (copy-pasteable):

```bash
cd BrachyBot
grep -rniE "fhir|ehrshot|hl7|redivis|mimic-cxr|chexprompt" --include=*.py web/ agent_runtime/ | wc -l   # 0
```

> Excluded items do **not** have their remote facts deleted; to cite them in a "methodology appendix", use
> the manifests in this directory.
