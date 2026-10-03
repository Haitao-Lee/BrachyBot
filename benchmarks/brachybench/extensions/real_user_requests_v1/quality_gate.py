"""Validate authoring contracts; never score a SUT or infer semantic validity.

This rejects mechanical/incomplete additions. Passing means structurally
auditable authoring data, not expert review, calibrated gold or live coverage.
"""
import math
import re

TRACKS = {"A", "B", "C", "D1", "D2", "D3", "E", "F", "G", "H", "I", "J", "K", "L", "M"}
ASSERTION_KINDS = {"effects", "state", "response", "dependency", "artifact", "outcome", "event_sequence", "evidence", "budget", "rendering"}

def validate(pack):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def finite(value, where):
        if isinstance(value, float):
            require(math.isfinite(value), f"{where}: non-finite number")
        elif isinstance(value, dict):
            for k, v in value.items():
                finite(v, f"{where}.{k}")
        elif isinstance(value, list):
            for index, v in enumerate(value):
                finite(v, f"{where}[{index}]")
    if not isinstance(pack, dict):
        return {"structural_ok": False, "errors": ["pack must be an object"], "formal_ready": False}
    require(pack.get("status") == "AUTHORING_ONLY", "pack: authoring-only status required")
    require(pack.get("formal_eligible") is False and pack.get("formal_results") == 0,
            "pack: cannot masquerade as formal evaluation")
    families = pack.get("families")
    if not isinstance(families, list) or not families:
        return {"structural_ok": False, "errors": errors + ["families missing"], "formal_ready": False}
    family_ids, case_ids, titles, protocols = set(), set(), set(), set()
    scenarios = []
    for fam in families:
        fid = fam.get("id", "")
        require(re.fullmatch(r"RUR-\d{2}", fid) is not None, f"{fid}: family identity invalid")
        require(fid not in family_ids, f"{fid}: duplicate family")
        family_ids.add(fid)
        require(text(fam.get("title")) and text(fam.get("gap")), f"{fid}: meaning/gap missing")
        require(fam.get("priority") in {"P0", "P1", "P2"}, f"{fid}: priority missing")
        require(bool(fam.get("tracks")) and set(fam.get("tracks", [])) <= TRACKS, f"{fid}: bad tracks")
        cases = fam.get("cases", [])
        require(len(cases) >= 2, f"{fid}: contextual contrast missing")
        for item in cases:
            scenarios.append(item)
            sid = item.get("id", "")
            require(re.fullmatch(r"RUR-\d{2}-\d{3}", sid) is not None, f"{sid}: scenario identity invalid")
            require(sid not in case_ids, f"{sid}: duplicate ID")
            case_ids.add(sid)
            require(item.get("family_id") == fid and item.get("split_group") == fid, f"{sid}: lineage/split family mismatch")
            require(item.get("primary_track") == fam.get("tracks", [None])[0], f"{sid}: owner mismatch")
            require(item.get("readiness") == "AUTHORING_ONLY" and item.get("formal_eligible") is False,
                    f"{sid}: unaudited candidate promoted")
            review = item.get("review", {})
            require(review.get("semantic_review") == "pending_independent_review" and review.get("live_validation") == "not_run",
                    f"{sid}: unearned review/live claim")
            title = item.get("title")
            require(text(title) and title not in titles, f"{sid}: missing/duplicate title")
            titles.add(title)
            initial = item.get("initial_state", {})
            require(initial.get("synthetic") is True and text(initial.get("case_id")) and text(initial.get("session_id")),
                    f"{sid}: synthetic case/session fence missing")
            require(isinstance(item.get("authorised_effects"), list), f"{sid}: explicit effect allowlist missing")
            require(all(text(x) for x in item.get("authorised_effects", [])), f"{sid}: empty authorised effect")
            require(len(item.get("forbidden_effects", [])) >= 2, f"{sid}: side-effect exclusions missing")
            steps = item.get("steps", [])
            require(bool(steps), f"{sid}: no real protocol")
            stimuli = []
            for step in steps:
                kind = step.get("kind")
                require(kind in {"user", "environment_event", "prior_exchange_fixture"}, f"{sid}: unsupported step")
                if kind == "user":
                    require(text(step.get("text")) and step.get("language") in {"zh", "en"}, f"{sid}: empty user turn/language")
                    stimuli.append((kind, step.get("text")))
                elif kind == "environment_event":
                    require(text(step.get("event")) and text(step.get("trigger")) and isinstance(step.get("payload"), dict),
                            f"{sid}: event without barrier/payload")
                    stimuli.append((kind, step.get("trigger"), step.get("event")))
                else:
                    require(text(step.get("user")) and text(step.get("assistant")), f"{sid}: incomplete prior history")
                    stimuli.append((kind, step.get("user"), step.get("assistant")))
            key = tuple(stimuli)
            require(key not in protocols, f"{sid}: exact duplicate protocol; do not count paraphrase padding")
            protocols.add(key)
            assertions = item.get("acceptance", [])
            require(len(assertions) >= 2, f"{sid}: insufficient outcome criteria")
            require(len({x.get("statement") for x in assertions}) == len(assertions), f"{sid}: duplicate criteria")
            require(all(x.get("kind") in ASSERTION_KINDS and text(x.get("statement")) for x in assertions),
                    f"{sid}: vague/unsupported acceptance")
            require(any(x.get("kind") in {"response", "artifact", "event_sequence", "outcome"} for x in assertions),
                    f"{sid}: absence of side effects alone is not task success")
            negatives = item.get("negative_controls", [])
            require(len(negatives) >= 3 and len(set(negatives)) == len(negatives) and all(text(x) for x in negatives),
                    f"{sid}: three distinct meaningful fault controls required")
            require(len(item.get("independent_evidence", [])) >= 3, f"{sid}: independent evidence missing")
            require(bool(item.get("adapter_requirements")), f"{sid}: unknown execution prerequisites")
            require(bool(item.get("budget")), f"{sid}: budget policy missing")
    require(pack.get("family_count") == len(families), "family count drift")
    require(pack.get("scenario_count") == len(scenarios), "scenario count drift")
    finite(pack, "pack")
    return {
        "structural_ok": not errors, "errors": errors,
        "families": len(families), "scenarios": len(scenarios),
        "negative_control_specs": sum(len(x.get("negative_controls", [])) for x in scenarios),
        "formal_ready": False, "semantic_validity": "NOT_ESTABLISHED",
        "live_runs": 0, "formal_results": 0,
        "reason": "Independent semantic review, runnable fixture/event drivers, calibrated response/visual references and live collectors remain required.",
    }
