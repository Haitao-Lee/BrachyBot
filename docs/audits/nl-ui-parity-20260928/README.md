# Natural Language / UI Parity Audit Attachment

Corresponds to the main report: `../../NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`.

Baseline: `a3aa976844526195756a36beebc2828b165e9c33`. All results were observed during the 2026-09-28 audit and do not represent behavior after fixes.

## Contents and Limitations

| File | Purpose |
|---|---|
| source_manifest.csv | Path, line count, and SHA-256 of all 505 scanned code files |
| static_controls.csv | 264 static interaction candidates in index.html, including event attributes |
| control_handler_index.csv | Inline calls for the above controls and candidate JS function locations; not a complete call graph |
| event_sites.csv | Lines containing the 568 JS/HTML event registrations or inline attributes, including matches in tests/libraries |
| production_routes.csv | 122 Flask route declarations in web/ |
| capability_registry.csv/json | All 111 registered targets of the UI tool and the full JSON schema |
| capability_source_index.csv | The registration line and frontend same-name string references for each target, used to locate the dispatcher; a reference is not proof of execution |
| test_inventory.csv | 1649 Python test function declarations; presence does not mean they were executed |
| inventory_summary.json | Counts and baseline |
| audit_probes.py/json | Semantics, authorization, dependency, and coverage results of actual pure functions in a synthetic context |
| audit_browser_probes.cjs/json | Actual production JS functions extracted into a Node VM and tested with lazy DOM stand-ins; no server access |
| audit_inventory.py | AST/HTML/event scanning script; input is tracked_sources.txt |
| tracked_sources.txt | Baseline of source file paths at audit time; only entries matching code extensions are used |
| validation_record.json | Actual test scope, passes, and environment blockers |

CSVs use a UTF-8 BOM so Chinese spreadsheet software can read them; JSON uses UTF-8. Console CJK encoding anomalies do not alter the original Chinese stored in the JSON.

**This attachment contains no real patient data, screenshots, or model invocation results.** The synthetic guide catalog and the 258-object fixture are merely reproducible boundary inputs. Dynamic DOM, in-canvas interactions, resource recovery, and GPU computation require real end-to-end verification.

Static scanning does not cover all dynamic behavior. In `capability_source_index.csv`, the absence of a literal reference does not mean there is no implementation, and the presence of a reference does not mean it is executable; the actual dispatch and postconditions must be read.

## Reproducing the Probes

It is recommended to copy the scripts into a temporary audit directory before running them, so the committed baseline JSON is not overwritten. The scripts only read the specified source code and write audit results to the directory containing the script; they do not call clinical tools, start services, or write cases.

```bash
REPO=/home/lht/snap/brachyplan/BrachyBot
AUDIT_DIR=$(mktemp -d /tmp/brachybot-parity-audit.XXXXXX)
cp "$REPO/docs/audits/nl-ui-parity-20260928/"{audit_probes.py,audit_browser_probes.cjs,audit_inventory.py,tracked_sources.txt} "$AUDIT_DIR/"
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python "$AUDIT_DIR/audit_probes.py" "$REPO"
node "$AUDIT_DIR/audit_browser_probes.cjs" "$REPO"
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python "$AUDIT_DIR/audit_inventory.py" "$REPO"
```

`audit_inventory.py` uses the old baseline path list. When auditing new files, regenerate the Git-tracked list and record the new HEAD, dirty diff, and hashes; do not claim full coverage while omitting newly added untracked files. The Python pure-function probes build package shims to avoid launching a heavy runtime on import, so the test scope is explicitly these functions, not the complete agent.

The JS probes rely on extracting function boundaries by name. If source refactoring causes extraction to fail, first update the probe's targeting or use an officially exported handler; this must not be interpreted as a business-logic pass.

These scripts print **observations** and do not assert a correct implementation. When fixing, encode the expected behavior from this report as formal assertions; for example, if a handler returns false it must not return success, the second independent step must execute, and 30/70 must be bound separately.

## Preventing Misuse of the Audit

- The 139 passed are for 11 targeted Python files, not the entire repository being green.
- Two isolated Node regressions passing does not mean real-browser screenshots/GPU/persistence pass.
- Three Playwright tests are missing dependencies locally and did not reach product assertions; they should not be marked as passed or as code failures.
- The risk items and pending E2E items in the main report must not be rewritten as clinical incidents that have already occurred.
- The main report only authorizes subsequent agents to formulate implementation based on evidence; this audit made no business-code changes, service restarts, or release operations.
