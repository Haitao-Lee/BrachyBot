# CT Cohort Inventory — 2026-10-04

This directory accompanies [`CT_COHORT_PLANNING_EXPERIMENT_DESIGN_2026-10-04.md`](../CT_COHORT_PLANNING_EXPERIMENT_DESIGN_2026-10-04.md). It is a **source inventory**, not a completed experiment or an eligibility certification.

## Contents

- `case_target_manifest.jsonl.gz`: all **40,299** source case/phase/target records, compressed without dropping fields. Actual existing CT inputs: **21,405**, comprising 20,808 NIfTI CTs and 597 DICOM CT studies. There are 39,349 NIfTI pair records, sharing 20,642 distinct CT paths; these include empty masks. Counts are not independent-patient totals.
- `pair_summary.json`: per-dataset target, input, phase and disposition counts.
- `inventory_summary.json`: file-type counts and inventory limits; file sizes were not collected.
- `metadata_accounting.json`: metadata/CT ID correspondence for PanTS, AbdomenAtlas and HECKTOR.
- `sample_image_qa.json`: 54 deterministically selected paired header/mask inspections, including empty controls and six near-integer encoding cases.
- `qa_summary.json`: sample and metadata aggregates; PSMA segment/reference information.
- `audit_totals.json`: reconciled input/pair/DICOM counts and unmatched dedicated-target check.
- `manifest_examples.json`: actual rows for inspection, not fabricated examples.
- `SHA256SUMS`: integrity hashes for the companion artifacts and README.

All source files remain untouched. Raw clinical prose, raw spreadsheet/CSV copies and raw DICOM UID inventories are not included. Source path/ID metadata and head/neck geometry must still be treated according to the original datasets' access/licensing rules; this package is not blanket authorization for public release.

## How to read a case

Python's standard library can stream the registry without extracting a 55+ MB JSONL file:

```python
import gzip
import json
from pathlib import Path

path = Path(__file__).parent / "case_target_manifest.jsonl.gz"
with gzip.open(path, "rt", encoding="utf-8") as stream:
    for line in stream:
        record = json.loads(line)
        if record["dataset"] == "KiTS21" and record["source_case_id"] == "case_00000":
            print(record["ct_path"])
            print(record["label_path"])
            print(record["target_values"])  # [2], not kidney 1 or cyst 3
```

The snippet is read-only; it does not upload, plan or certify the case. In an interactive notebook use an explicit absolute manifest path instead of `__file__`.

Filter by `dataset`, `source_case_id`, `phase`, and `target_semantics`, not display names. An actual source path is nonempty only when the corresponding input was enumerated. `expected_ct_path`/`expected_label_path` describe declared locations and do not prove existence. MRI rows have an `image_path` but no `ct_path`. DICOM `ct_path` is a series directory, and `target_values` are DICOM segment numbers, not a ready-to-upload array.

Use `inventory_status` to distinguish enumerated pairs, existing unlabeled test scans, missing CT/unlabeled tests, excluded MRI and DICOM conversion requirements. `metadata_positive` is a screening flag, not voxel truth or confirmed malignancy. The sampled AbdomenAtlas colon case `BDMAP_00002193` illustrates a nonempty mask with a false volume-derived metadata flag.

`voxel_validation=NOT_RUN`, `geometry_validation=NOT_RUN`, `clinical_eligibility=NOT_ESTABLISHED` and `planning_profile_id=null` are deliberate. Limited `sample_*` evidence does not satisfy the complete future preflight. No result file contains a planning-success measurement.

## Critical input rule

For the real-user experiment, upload the validated CT and discrete selected-label mask through the browser. The mask initially becomes **Upload Mask**. Select the declared tumor child or children using stable IDs and perform **Move to CTV**. Independently verify the durable effective target and its Planning provenance before submitting a planning request. Upload success or a raw path field does not satisfy this gate.

See the parent specification for source-label maps, derivative/geometry rules, reviewed planning-profile requirements, browser orchestration, asynchronous completion, artifact verification, failure recovery and statistical analysis.
