"""Frozen institutional/protocol/budget gates. Templates confer no approval."""
from pathlib import Path
from .core import Blocked, digest, load_json, sha256


def gates(cfg, storage, execute=False, enforce_deadline=True):
    documents = {}
    for name in ("governance", "protocol", "acceptance_rules", "budget"):
        path = cfg.get(name + "_path")
        if not path or not Path(path).is_file():
            raise Blocked(name.upper() + "_UNRESOLVED")
        documents[name] = load_json(path)
    g, p, a, b = (documents[n] for n in ("governance", "protocol", "acceptance_rules", "budget"))
    if g.get("status") != "APPROVED" or not g.get("institutional_determination") or not g.get("data_steward"):
        raise Blocked("GOVERNANCE_UNRESOLVED")
    if g.get("nas_server_acl_verified") is not True or not g.get("permitted_datasets") or g.get("model_data_flow_approved") is not True:
        raise Blocked("DATA_ACCESS_OR_FLOW_UNRESOLVED")
    if p.get("status") != "FROZEN" or not p.get("investigator") or not p.get("frozen_at") or type(p.get("sampling_seed")) is not int:
        raise Blocked("PROTOCOL_NOT_FROZEN")
    if p.get("study_kind") not in {"descriptive_pilot", "descriptive_stress", "paired_workflow"}:
        raise Blocked("UNKNOWN_STUDY_KIND")
    if p.get("study_kind") == "paired_workflow" and (p.get("arms") != ["browser-chat", "manual-ui"] or not p.get("analysis") or not p.get("sample_size_basis")):
        raise Blocked("PAIRED_PROTOCOL_INCOMPLETE")
    from .cohort import load_frame, primary_endpoint, row_ids
    primary_endpoint(p)
    if not isinstance(p.get("arms"), list) or not p["arms"] or len(p["arms"]) != len(set(p["arms"])) or not set(p["arms"]) <= {"browser-chat", "manual-ui"}:
        raise Blocked("INVALID_REGISTERED_ARMS")
    if not a.get("reviewer") or a.get("status") != "FROZEN" or not a.get("guide_checks") or not a.get("report_checks"):
        raise Blocked("ACCEPTANCE_RULES_UNRESOLVED")
    required = a["guide_checks"] + a["report_checks"]
    if len(required) != len(set(required)) or not a.get("frozen_at"):
        raise Blocked("ACCEPTANCE_RULES_INCOMPLETE")
    for name in required:
        rule = a.get("criteria", {}).get(name, {})
        if not all(rule.get(k) for k in ("method", "pass_rule", "owner", "evidence_requirement")):
            raise Blocked("ACCEPTANCE_CRITERION_UNRESOLVED", name)
    if b.get("status") != "APPROVED" or not b.get("owner") or not b.get("max_attempts") or not b.get("max_retained_bytes") or not b.get("deadline_utc"):
        raise Blocked("RESOURCE_BUDGET_UNRESOLVED")
    if not b.get("approved_account_quota_bytes") or not cfg.get("model_recipe"):
        raise Blocked("ACCOUNT_QUOTA_OR_MODEL_RECIPE_UNRESOLVED")
    if any(type(b.get(k)) is not int or b[k] <= 0 for k in ("max_attempts", "max_retained_bytes", "approved_account_quota_bytes")):
        raise Blocked("INVALID_RESOURCE_BUDGET")
    if any(type(v) not in (int, float) or not 0 < v < float("inf") for v in cfg.get("budgets", {}).values()):
        raise Blocked("INVALID_TIMEOUT_BUDGET")
    if not {"upload_s", "workflow_s", "guide_s", "report_s", "export_s", "overall_s"} <= set(cfg.get("budgets", {})):
        raise Blocked("TIMEOUT_BUDGET_INCOMPLETE")
    frame = load_frame(p, storage, cfg)
    identifiers = row_ids(p, frame)
    if not identifiers or any(not isinstance(i, str) or not i for i in identifiers) or len(identifiers) != len(set(identifiers)):
        raise Blocked("SAMPLING_FRAME_NOT_FROZEN")
    from datetime import datetime, timezone
    deadline = datetime.fromisoformat(b["deadline_utc"].replace("Z", "+00:00"))
    if deadline.tzinfo is None or enforce_deadline and deadline <= datetime.now(timezone.utc):
        raise Blocked("RESOURCE_DEADLINE_EXPIRED")
    if cfg.get("max_experiment_bytes") != b["max_retained_bytes"]:
        raise Blocked("BUDGET_CONFIG_MISMATCH")
    # Keep the large frame out of the protocol hash payload: its exact file
    # bytes are already pinned by the protocol. Persist the resolved snapshot
    # once, not once per dispatched case.
    documents["hash"] = digest(documents)
    if frame:
        documents["cohort_frame"] = frame
    if execute:
        frozen = storage.path("protocol/frozen-gates.json")
        if frozen.exists() and load_json(frozen)["hash"] != documents["hash"]:
            raise Blocked("FROZEN_PROTOCOL_DRIFT")
        from .core import atomic_json
        if not frozen.exists():
            atomic_json(frozen, documents)
    return documents


def approvals(path):
    from .preflight import records
    import json
    result = {}
    if path and Path(path).is_file():
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r["row_id"] in result:
                    raise Blocked("DUPLICATE_CASE_APPROVAL")
                result[r["row_id"]] = r
    return result


def approved_row(row, receipt):
    if not receipt or receipt.get("status") != "APPROVED_RESEARCH" or not receipt.get("reviewer") or not receipt.get("reviewed_at"):
        raise Blocked("CASE_APPROVAL_UNRESOLVED", row["row_id"])
    if receipt.get("target_hash") != row.get("target_hash") or receipt.get("source_hashes") != row.get("source_hashes"):
        raise Blocked("CASE_APPROVAL_SOURCE_MISMATCH")
    return {**row, "clinical_eligibility": "APPROVED_RESEARCH", "planning_profile_id": receipt.get("profile_id"),
            "case_approval": receipt, "inference_cluster_id": receipt.get("reviewed_cluster_id") or row.get("ct_content_hash"),
            "patient_linkage_resolved": bool(receipt.get("reviewed_cluster_id"))}
