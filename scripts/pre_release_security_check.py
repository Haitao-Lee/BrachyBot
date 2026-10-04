"""Read-only release gates. This does not install packages or restart services."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

# Support both `python scripts/...py` and imports by the regression suite.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.credential_audit import load_incidents, scan_sources, scan_processes, discover_processes


def checks(root, *, scan_roots=(), pids=None, incident_file=None, coverage=None):
    root = Path(root).resolve()
    findings = []
    try:
        version = importlib.metadata.version("torch")
        numbers = tuple(int(part) for part in re.match(r"^(\d+)\.(\d+)\.(\d+)", version).groups())
        if numbers < (2, 10, 0):
            findings.append({"id": "torch_checkpoint_cve", "severity": "block", "message": f"Installed torch {version} is affected by CVE-2026-24747; validate an isolated >=2.10.0 release stack."})
    except (importlib.metadata.PackageNotFoundError, AttributeError):
        findings.append({"id": "torch_missing_or_unknown", "severity": "block", "message": "Cannot verify the installed PyTorch version."})
    for variable in ("BRACHYBOT_ALLOW_INSECURE_REMOTE", "BRACHYBOT_DEBUG_ACCOUNT_ENABLED", "BRACHYBOT_ALLOW_SELF_REGISTRATION"):
        if os.environ.get(variable, "0").lower() in {"1", "true", "yes", "on"}:
            findings.append({"id": variable.lower(), "severity": "block", "message": "A development/enrollment override is enabled; it must not be inherited by the public release."})
    incidents, incident_findings = load_incidents(incident_file or root / "scripts/compromised_credentials.json")
    findings.extend(incident_findings)
    if any(item["revocation_status"] != "revoked" for item in incidents):
        findings.append({"id": "credential_revocation_unverified", "severity": "block",
                         "message": "Provider-side revocation has not been independently confirmed. Local removal is insufficient."})
    source_findings, source_scope = scan_sources([*scan_roots, root], incidents)
    findings.extend(source_findings)
    selected_pids = discover_processes(root) if pids is None else pids
    process_findings, process_scope = scan_processes(selected_pids, incidents)
    findings.extend(process_findings)
    if not selected_pids:
        findings.append({"id": "no_service_environment_inspected", "severity": "review",
                         "message": "No service process was selected/found; launch-environment validation is still required."})
    if coverage is not None:
        coverage.update({"sources": source_scope, "processes": process_scope,
                         "torch_interpreter": sys.executable,
                         "limitations": "No Git-history, compressed-archive, patient/model-data or provider-portal validation. Source matches and environment values are never printed."})
    findings.append({"id": "manual_release_requirements", "severity": "review", "message": "This check is not a penetration test. Require credential rotation, a hash-locked release environment, checkpoint provenance, TLS/Access configuration, browser concurrency and real-case release validation."})
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--scan-root", type=Path, action="append", default=[], help="Additional checkout, backup, or log root (read-only)")
    parser.add_argument("--pid", type=int, action="append", help="Inspect selected same-user service environment; default discovers checkout-cwd processes")
    parser.add_argument("--incident-file", type=Path, help="SHA256-only incident registry; never a raw credential file")
    args = parser.parse_args()
    coverage = {}
    findings = checks(args.root, scan_roots=args.scan_root, pids=args.pid, incident_file=args.incident_file, coverage=coverage)
    blocked = any(item["severity"] == "block" for item in findings)
    print(json.dumps({"release_gate": "blocked" if blocked else "manual_review_required", "findings": findings, "coverage": coverage}, indent=2))
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
