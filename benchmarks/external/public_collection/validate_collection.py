"""Record construction provenance/inventory without model/API/GPU evaluation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import zipfile

from .collect import ROOT, read_json, sha256, verify, write_json
from .pool import PublicPool


def validate(root=ROOT, run_tests=False):
    root = Path(root).resolve()
    integrity = verify(root)
    if integrity["problems"]:
        raise ValueError("asset integrity failure: " + repr(integrity["problems"]))
    entries = read_json(root / "catalog.json")["benchmarks"]
    summaries = [PublicPool(e["id"], root).summary() for e in entries]
    crosscheck = read_json(root / "official_hf_checksum_crosscheck.json")
    lock = read_json(root / "assets.lock.json")
    if len(crosscheck["records"]) != crosscheck["checked_lfs_files"] or any(
        lock["files"][r["path"]]["sha256"] != r["official_lfs_sha256"] for r in crosscheck["records"]):
        raise ValueError("official public checksum crosscheck drift")
    with zipfile.ZipFile(root / "assets/EXT-18/data/images.zip") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError("image archive CRC failure: " + bad)
    result = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_audit_date": "2026-10-03",
        "evaluation_mode": "construction_validation_not_sut_evaluation",
        "sut_runs": 0, "model_calls": 0, "paid_judge_calls": 0,
        "protocol_fidelity_certified": False, "comparable_sut_result": False,
        "catalog_sha256": sha256(root / "catalog.json"),
        "asset_lock_sha256": sha256(root / "assets.lock.json"),
        "selection_sha256": sha256(root / "selection.json"),
        "integrity": integrity, "images_archive_crc": "passed",
        "official_hf_lfs_checksum_crosscheck": {"files": crosscheck["checked_lfs_files"], "mismatches": 0},
        "benchmarks": summaries,
        "construction_tests": {"executed": False}
    }
    if run_tests:
        command = [sys.executable, "-m", "pytest", str(root / "tests"), "-q", "--tb=short"]
        process = subprocess.run(command, cwd=root.parent, text=True, capture_output=True)
        result["construction_tests"] = {"executed": True, "command": command,
            "exit_code": process.returncode, "output": process.stdout + process.stderr,
            "purpose": "contract/scorer controls; not measured agent outputs"}
        if process.returncode:
            write_json(root / "construction_validation.json", result)
            raise ValueError("construction tests failed; see construction_validation.json")
    write_json(root / "construction_validation.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tests", action="store_true")
    args = p.parse_args()
    r = validate(run_tests=args.tests)
    print("construction valid; collections=" + str(len(r["benchmarks"])) + "; SUT/model/judge calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
