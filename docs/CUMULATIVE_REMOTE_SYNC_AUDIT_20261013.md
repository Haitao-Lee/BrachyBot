# Cumulative source synchronization audit — 2026-10-13

Scope: the entire extracted local `timepoints-implementation-20261010`
candidate for the cumulative a–i feature, not today's isolated patch alone and
not unrelated historical branches elsewhere in the parent SSH workspace.

The reconstruction baseline combines, in order:
`source.tar`, `extra-source.tar`, `followup-source-20261011.tar`, and
`work/source-completion-20261011.tar.gz`. It therefore retains the actual
already-dirty project baseline rather than pretending every change since Git HEAD
belongs to this task.

The initial cumulative delivery had **254 changed files**:

| Category | Files | New files | Added lines | Removed lines |
|---|---:|---:|---:|---:|
| Product code/configuration | 128 | 56 | 22,454 | 1,598 |
| Tests | 108 | 81 | 13,325 | 76 |
| Documentation/evidence | 18 | 18 | 31,178 | 0 |

Counts compare UTF-8 text split into lines using difflib, ignoring line-ending
differences for line counts but not file hash checks. These are changed-line
statistics, not net newly invented feature lines. Documentation includes JSON
evidence; it is not all executable code. The final audit/handoff updates add this
document and revise existing documents; consult the generated final inventory
for their current exact counts.

The broader initial scan checked **2046 local files**, including unchanged
baseline Python/JS/CSS/HTML/JSON, deployment helper scripts, documentation,
CSV and PNG assets. It found **2036 exact hash matches** and **10 missing
unchanged baseline files**. None of the 254 changed files was omitted.
The omitted baseline files were:

- `deploy/public/check_public.py`, `create_account.py`, `README.md`,
  `requirements.txt`, `VALIDATION.md`;
- `examples/usage_examples.py`;
- root `PLANNING_REFACTOR_SUMMARY.md`, `README.md`, `report.json`,
  `treatment_plan.json`.

They are explicitly included in the baseline-completion archive, rather than
silently disregarded. Final per-file verification is generated into the remote
stage's `cumulative-complete-source-verification-20261013.json` and copied locally.
The inventory also checks for cumulative changes absent from the delivery
manifest and baseline paths accidentally deleted locally. Zero omissions in that
report are the synchronization gate; transfer command success alone is not.

Excluded intentionally: temporary `work`, source tarballs, Python caches,
`.runtime`, Git metadata, dependency/model directories, and unrelated historical
checkouts. These are not cumulative product source modifications. Source-model
bundles already installed on the remote host remain separately configured.
No production patient runtime is copied into this source handoff.

Remote target:
`/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/product-browser-checkout`
on `rtx3090_external`. LAN/public production code and processes are not updated.
This is temporary isolated storage, not a production launch or durable Git push.

The tested frozen archive is retained unchanged. Its runtime skill-registry file
was regenerated with different `created_at`/`last_used` values for 28 skills;
an explicit JSON comparison found only those two timestamp fields differing.
Source-definition equivalence is checked against the immutable archive used to
start that regression, not by overwriting the executed freeze to hide drift.

Latest full regression: **4506 passed, 1 failed, 2 skipped, 4 passing subtests**.
The failed native guide-browser test returned `guide_source_image_unverified`.
Synchronization completion does not imply complete functional acceptance.
