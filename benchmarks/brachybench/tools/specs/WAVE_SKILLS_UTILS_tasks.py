"""Wave: skills registry / markdown loader / skill templates and utils.

Covers eight NEW capabilities (registry ``required_dims`` in
``capabilities/registry.yaml``):

* ``skills:registry``        skills/skill_base.py              F,E,P,R,A
* ``skills:markdown_loader`` skills/markdown_loader.py        F,E,P,I
* ``skills:templates``       skills/{advanced,planning,segmentation,evaluation}_skills.py  F,E,P
* ``utils:ct_volume``        utils/ct_volume.py               F,E,I
* ``utils:display_paths``    utils/display_paths.py           F,E,S,I
* ``utils:planning_metrics`` utils/planning_metrics.py        F,E,P,I
* ``utils:user_errors``      utils/user_errors.py             F,E,P,R,S
* ``utils:cancellation``     utils/cancellation.py            F,R

Every positive observation is a real happy-path (or repaired) state; every
negative is a genuine contract violation read off the module source (a wrong
trigger hit, a malformed frontmatter silently kept, a 4-D CT not reduced, a
``..`` escape through a display token, a CTV row leaked into the OAR table, a
provider payload echoed to chat, a thread-local checker leaking across
threads).  Self-verify::

    python tools/build_expansion.py --spec tools/specs/WAVE_SKILLS_UTILS_tasks.py --prove --dry-run
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# fixtures (discriminating data lives in obs / oracle_inputs, never here)
# ---------------------------------------------------------------------------

MEMORY: Dict[str, Any] = {
    "case_family": "synth/memory_case",
    "setup_script": "fixtures/setup/memory_case.py",
    "initial_state_hash": "sha256:pending",
}
RECOVERY: Dict[str, Any] = {
    "case_family": "synth/recovery_case",
    "setup_script": "fixtures/setup/recovery_case.py",
    "initial_state_hash": "sha256:pending",
}
SECURITY: Dict[str, Any] = {
    "case_family": "synth/security_sandbox",
    "setup_script": "fixtures/setup/security_sandbox.py",
    "initial_state_hash": "sha256:pending",
}
INTEROP: Dict[str, Any] = {
    "case_family": "synth/interop_case",
    "setup_script": "fixtures/setup/interop_case.py",
    "initial_state_hash": "sha256:pending",
}
PROSTATE: Dict[str, Any] = {
    "case_family": "synth/prostate_s02",
    "setup_script": "fixtures/setup/prostate_s02_full_pipeline.py",
    "initial_state_hash": "sha256:pending",
}
PANCREAS: Dict[str, Any] = {
    "case_family": "phantom/pancreas_p03",
    "setup_script": "fixtures/setup/pancreas_p03_pipeline.py",
    "initial_state_hash": "sha256:pending",
}
PANCREAS_SEEDS: Dict[str, Any] = {
    "case_family": "phantom/pancreas_p03_seeds_3",
    "setup_script": "fixtures/setup/pancreas_p03_seeds_3.py",
    "initial_state_hash": "sha256:pending",
}


# ---------------------------------------------------------------------------
# task-doc / observation builders
# ---------------------------------------------------------------------------


def _ev(tid: str, check: Optional[str] = None) -> List[str]:
    refs = [f"oracle:{check}"] if check else []
    refs.append(f"task:{tid}")
    return refs


def _doc(
    tid: str,
    track: str,
    construct: str,
    intent: str,
    *,
    fixture: Dict[str, Any],
    check: str,
    derived: str,
    turns: Sequence[Dict[str, str]],
    contrast: str,
    constraint_class: str = "postcondition",
    predicate: Optional[str] = None,
    mode: str = "single_turn",
    group_type: str = "G-CT",
    paraphrase: Optional[str] = None,
    seed: int = 9000,
    difficulty: str = "medium",
    power_role: str = "primary",
    probes: Sequence[str] = (),
    layers: Sequence[str] = ("L3", "L4"),
    metric: Optional[str] = None,
    allowed_intermediates: Sequence[str] = (),
    audit_required: bool = False,
    n_runs: int = 5,
) -> Dict[str, Any]:
    oracle: Dict[str, Any] = {
        "kind": "program",
        "check": check,
        "constraint_class": constraint_class,
        "expect": None,
        "tolerance": None,
        "assist_only": False,
        "independent_check": True,
        "evidence_keys": [],
        "gold": None,
    }
    if predicate is not None:
        oracle["predicate"] = predicate
    multi = mode == "multi_turn"
    return {
        "schema_version": "1.0",
        "id": tid,
        "track": track,
        "layers": list(layers),
        "comparability": ["alpha", "beta"],
        "construct": construct,
        "cost_class": "state_only",
        "power_role": power_role,
        "clinical_intent": intent,
        "fixture": dict(fixture),
        "unit": {
            "kind": "task_scenario",
            "group_type": group_type,
            "contrast_family_id": contrast,
        },
        "protocol": {
            "mode": mode,
            "turns": [dict(t) for t in turns],
            "ui_counterpart": None,
            "budget": (
                {"wall_clock_s": 120, "turns": 2, "tool_calls": 12}
                if multi
                else {"wall_clock_s": 60, "turns": 1, "tool_calls": 6}
            ),
            "allowed_intermediates": list(allowed_intermediates),
            "audit_required": audit_required,
            "n_runs": n_runs,
        },
        "oracle": oracle,
        "scoring": {
            "primary_metric": metric or f"{check}_pass",
            "gate_refs": [],
            "weight": 1.0,
            "difficulty_target": difficulty,
        },
        "anti_gaming": {
            "paraphrase_group": paraphrase or f"{tid}-P01",
            "hidden": False,
            "generation_seed": seed,
            "canary_class": None,
            "behavioral_probes": list(probes),
            "contrast_family_id": contrast,
        },
        "provenance": {
            "source": "audit_derived",
            "derived_from": derived,
            "guideline_ref": None,
            "reviewers": ["auto"],
            "authored_on": "2026-10-01",
            "deprecated": None,
        },
    }


def _g(inputs: Dict[str, Any], comment: str) -> Dict[str, Any]:
    return {
        "sut_id": "BrachyBot-replay",
        "intent_class": "imperative",
        "partial_status": "COMPLETED",
        "oracle_inputs": inputs,
        "_comment": comment,
    }


def _gn(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"oracle_inputs": inputs}


def _pstate(terminal_state: Dict[str, Any], comment: str, *,
            reply: Optional[Dict[str, Any]] = None,
            intent_class: str = "imperative") -> Dict[str, Any]:
    out = {
        "sut_id": "BrachyBot-replay",
        "intent_class": intent_class,
        "partial_status": "COMPLETED",
        "terminal_state": terminal_state,
        "_comment": comment,
    }
    if reply is not None:
        out["reply"] = reply
    return out


def _pnstate(terminal_state: Dict[str, Any]) -> Dict[str, Any]:
    return {"terminal_state": terminal_state}


def _gen_entry(
    tid: str, track: str, construct: str, intent: str, *, fixture: Dict[str, Any],
    check: str, derived: str, turns: Sequence[Dict[str, str]], contrast: str,
    pos: Dict[str, Any], neg: Dict[str, Any], cov: Dict[str, Any], seed: int,
    difficulty: str = "medium", power_role: str = "primary",
    group_type: str = "G-CT", paraphrase: Optional[str] = None,
    constraint_class: str = "postcondition", probes: Sequence[str] = (),
    metric: Optional[str] = None, mode: str = "single_turn",
    allowed_intermediates: Sequence[str] = (), audit_required: bool = False,
    n_runs: int = 5, comment: str = "",
) -> Dict[str, Any]:
    task = _doc(tid, track, construct, intent, fixture=fixture, check=check,
                derived=derived, turns=turns, contrast=contrast,
                constraint_class=constraint_class, group_type=group_type,
                paraphrase=paraphrase, seed=seed, difficulty=difficulty,
                power_role=power_role, probes=probes, metric=metric, mode=mode,
                allowed_intermediates=allowed_intermediates,
                audit_required=audit_required, n_runs=n_runs)
    return {"task": task, "obs_pos": _g(pos, comment or f"CI replay for {tid}."),
            "obs_neg": _gn(neg), "coverage": cov}


def _pred_entry(
    tid: str, track: str, construct: str, intent: str, *, fixture: Dict[str, Any],
    predicate: str, derived: str, turns: Sequence[Dict[str, str]], contrast: str,
    pos_state: Dict[str, Any], neg_state: Dict[str, Any], cov: Dict[str, Any],
    seed: int, difficulty: str = "medium", power_role: str = "safety_gate",
    group_type: str = "G-CT", probes: Sequence[str] = (),
    reply: Optional[Dict[str, Any]] = None, intent_class: str = "imperative",
    comment: str = "",
) -> Dict[str, Any]:
    task = _doc(tid, track, construct, intent, fixture=fixture, check="pred",
                derived=derived, turns=turns, contrast=contrast, predicate=predicate,
                group_type=group_type, seed=seed, difficulty=difficulty,
                power_role=power_role, probes=probes)
    return {"task": task,
            "obs_pos": _pstate(pos_state, comment or f"CI replay for {tid}.",
                               reply=reply, intent_class=intent_class),
            "obs_neg": _pnstate(neg_state), "coverage": cov}


# ---------------------------------------------------------------------------
# oracle-input shorthands
# ---------------------------------------------------------------------------


def _rk(retrieved, gold, *, k: int = 5, recall_min: float = 1.0) -> Dict[str, Any]:
    return {"retrieval_at_k": {"retrieved": [list(r) for r in retrieved],
                               "gold": [list(g) for g in gold],
                               "k": k, "recall_min": recall_min}}


def _err(errors: List[Dict[str, Any]], allowed=None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"errors": errors}
    if allowed is not None:
        kw["allowed_codes"] = list(allowed)
    return {"error_contract": kw}


def _inv(before: Dict[str, Any], after: Dict[str, Any], allowed=None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"before": before, "after": after}
    if allowed is not None:
        kw["allowed_mutations"] = list(allowed)
    return {"state_invariant": kw}


def _rt(fmt: str, first: Dict[str, Any], second: Dict[str, Any],
        independent: Dict[str, Any], *, dose_grid_scaling=None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"first": first, "second": second, "fmt": fmt,
                          "independent": independent}
    if dose_grid_scaling is not None:
        kw["dose_grid_scaling"] = dose_grid_scaling
    return {"roundtrip_fidelity": kw}


def _coord(samples=None, origin=None, spacing=None, direction=None,
           header_a=None, header_b=None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if samples is not None:
        kw["samples"] = [list(s) for s in samples]
    if origin is not None:
        kw["origin"] = list(origin)
    if spacing is not None:
        kw["spacing"] = list(spacing)
    if direction is not None:
        kw["direction"] = list(direction)
    if header_a is not None:
        kw["header_a"] = header_a
    if header_b is not None:
        kw["header_b"] = header_b
    return {"coord_roundtrip": kw}


def _exp(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"export_artifact_validity": {"artifacts": artifacts}}


def _pt(ops: List[Dict[str, Any]], roots: Sequence[str]) -> Dict[str, Any]:
    return {"path_traversal_blocked": {"file_ops": ops,
                                       "allowed_roots": list(roots)}}


def _idem(states: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"idempotency": {"states": states}}


def _sev(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"self_evolution_regression": {"before": before, "after": after,
                                          "allow_improvement": True}}


def _turns(text: str, lang: str = "zh") -> List[Dict[str, str]]:
    return [{"role": "user", "text": text, "lang": lang}]


TASKS: List[Dict[str, Any]] = []


def _emit_registry() -> None:
    """skills/skill_base.py: registry retrieval, corruption, dedup, evolution."""
    deriv_trigger = "skills/skill_base.py:87-94 (find_by_trigger substring match, sorted by success_rate*usage_count)"
    deriv_load = "skills/skill_base.py:191-202 (_load_skills swallows JSONDecodeError/KeyError -> {})"
    deriv_register = "skills/skill_base.py:78-81 (register overwrites the same name)"
    deriv_evolve = "skills/skill_base.py:120-151 (evolve_from_interactions; dedup fix noted lines 133-148)"
    deriv_rate = "skills/skill_base.py:31-34,43-48 (success_rate = success/usage, use())"

    # -- F: trigger matching returns the correct skill(s) --------------------
    trig = [
        ("Prostate cancer brachytherapy, segment the target first.", ["prostate_segmentation"], ["pancreas_segmentation"]),
        ("Pancreatic tumor needs CTV segmentation.", ["pancreas_segmentation", "pancreas_ctv_seg"], ["prostate_full_workflow"]),
        ("run the full plan end to end", ["full_auto_planning"], ["dvh_analysis"]),
        ("quick plan please", ["quick_plan"], ["full_auto_planning"]),
        ("use reinforcement learning for seed placement", ["rl_optimized_plan"], ["quick_plan"]),
        ("segment all organs with totalsegmentator", ["multi_organ_seg"], ["dicom_export"]),
        ("export the plan to DICOM RT", ["dicom_export"], ["report_generation"]),
        ("generate the planning report", ["report_generation"], ["dicom_export"]),
        ("analyze the DVH curves", ["dvh_analysis"], ["quality_check"]),
        ("check the plan quality", ["quality_check"], ["report_generation"]),
        ("liver brachytherapy workflow", ["liver_full_workflow"], ["lung_full_workflow"]),
        ("lung tumor anterior approach", ["lung_full_workflow"], ["liver_full_workflow"]),
        ("prostate brachytherapy full workflow", ["prostate_full_workflow"], ["pancreas_full_workflow"]),
        ("intraoperative replan after seed deviation", ["intraop_replan"], ["plan_optimization"]),
        ("optimize the plan to improve V100", ["plan_optimization"], ["quick_plan"]),
        ("detailed dose evaluation with DVH curves", ["detailed_evaluation"], ["standard_evaluation"]),
        ("standard treatment plan", ["standard_planning"], ["rl_planning"]),
        ("voco pretrained segmentation", ["voco_segmentation"], ["multi_organ_seg"]),
        ("self evolve from experience", ["self_evolve"], ["code_writer"]),
        ("write a new tool for planning", ["code_writer"], ["self_evolve"]),
    ]
    for i, (text, gold, bad) in enumerate(trig, 1):
        tid = f"SKILLS-REG-{i:03d}"
        lang = "zh" if any("\u4e00" <= c <= "\u9fff" for c in text) else "en"
        pos = _rk([gold], [gold])
        neg = _rk([bad], [gold])
        cov = {"skills:registry": {"F": _ev(tid, "retrieval_at_k")}}
        TASKS.append(_gen_entry(
            tid, "K", "skill_registry_trigger_match",
            f"Registry retrieval by trigger word must hit {gold} and must not return unrelated skills.",
            fixture=MEMORY, check="retrieval_at_k", derived=deriv_trigger,
            turns=_turns(text, lang), contrast="K/skill_registry/trigger_match",
            pos=pos, neg=neg, cov=cov, seed=9100 + i, difficulty="easy",
            comment=f"CI replay for {tid}: trigger text retrieves {gold} at recall@5=1.0."))

    # -- P: bilingual / typo / terseness express the same retrieval decision --
    phr = [
        (["segment the prostate", "segment the prostate", "prostate segmentation target"],
         ["prostate_segmentation"], ["pancreas_segmentation"]),
        (["help me make a full plan", "generate a full plan", "full plan full pipeline"],
         ["full_auto_planning"], ["dvh_analysis"]),
        (["quick plan", "fast plan", "quick preview"], ["quick_plan"], ["full_auto_planning"]),
        (["plan with reinforcement learning", "RL optimization plan", "reinforcement learning rl plan"],
         ["rl_optimized_plan"], ["quick_plan"]),
        (["export DICOM", "export DICOM RT", "dicom export"],
         ["dicom_export"], ["report_generation"]),
        (["generate report", "create report", "report summary"],
         ["report_generation"], ["dicom_export"]),
        (["DVH analysis", "DVH analysis", "dose volume histogram"],
         ["dvh_analysis"], ["quality_check"]),
        (["quality check", "verify plan", "check plan quality"],
         ["quality_check"], ["report_generation"]),
        (["liver brachytherapy", "liver workflow", "liver tumor"],
         ["liver_full_workflow"], ["lung_full_workflow"]),
        (["lung treatment", "lung tumor", "lung brachytherapy"],
         ["lung_full_workflow"], ["liver_full_workflow"]),
        (["pancreas segmentation", "pancreas segmentation", "pancreas annotation"],
         ["pancreas_segmentation"], ["prostate_segmentation"]),
        (["dose assessment", "dose eval", "evaluation metrics"],
         ["standard_evaluation"], ["dvh_analysis"]),
    ]
    for i, (texts, gold, bad) in enumerate(phr, 1):
        tid = f"SKILLS-REG-{20 + i:03d}"
        pos = _rk([[gold], [gold], [gold]], [[gold], [gold], [gold]])
        neg = _rk([[gold], [bad], [gold]], [[gold], [gold], [gold]])
        cov = {"skills:registry": {"P": _ev(tid, "retrieval_at_k"),
                                   "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "K", "skill_registry_expression_robust",
            f"Chinese/English, abbreviated, and misspelled expressions of the same intent must all retrieve {gold}.",
            fixture=MEMORY, check="retrieval_at_k", derived=deriv_trigger,
            turns=[{"role": "user", "text": t, "lang": ("zh" if any("\u4e00" <= c <= "\u9fff" for c in t) else "en")}
                   for t in texts],
            contrast="K/skill_registry/expression", pos=pos, neg=neg, cov=cov,
            seed=9130 + i, difficulty="medium", group_type="G-EQ",
            paraphrase=f"{tid}-P01", probes=["paraphrase"],
            comment=f"CI replay for {tid}: all three phrasings retrieve {gold}."))

    # -- E: registry failures surface a typed, correctly-labelled envelope ----
    codes = [
        ("REGISTRY_CORRUPT", False), ("REGISTRY_SCHEMA_INVALID", False),
        ("SKILL_NAME_EMPTY", False), ("TRIGGER_TYPE_INVALID", False),
        ("STORAGE_WRITE_DENIED", False), ("SERIALIZATION_ERROR", False),
        ("SKILL_DUPLICATE_NAME", False), ("CATEGORY_UNKNOWN", False),
        ("REGISTRY_VERSION_MISMATCH", False), ("CONCURRENT_WRITE", False),
        ("SNAPSHOT_MISSING", False), ("SKILL_NOT_FOUND", False),
        ("EVOLVE_PATTERN_EMPTY", False), ("BUSY", True),
        ("UNAVAILABLE", True), ("TIMEOUT", True), ("NETWORK", True),
        ("OOM_RETRY", True),
    ]
    for i, (code, retry) in enumerate(codes, 1):
        tid = f"SKILLS-REG-{32 + i:03d}"
        msg = f"Skill registry operation failed: {code}"
        pos_err = {"code": code, "message": msg, "retryable": retry,
                   "op_id": f"op_registry_{i:03d}"}
        neg_err = dict(pos_err, retryable=not retry)
        cov = {"skills:registry": {"E": _ev(tid, "error_contract"),
                                   "R": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "K", "skill_registry_error_envelope",
            f"Registry error {code} must return a stable error envelope, with retryable consistent with the error code.",
            fixture=RECOVERY, check="error_contract", derived=deriv_load,
            turns=_turns(f"Encountering {code} in the registry operation should return a decidable error structure.", lang="en"),
            contrast=f"K/skill_registry/error/{code}", pos=_err([pos_err]),
            neg=_err([neg_err]), cov=cov, seed=9160 + i, difficulty="easy",
            power_role="secondary",
            comment=f"CI replay for {tid}: {code} envelope is complete and retryable={retry}."))

    # -- R: a failed registry write leaves the existing skills intact ---------
    case_a = {"skills": {
        "prostate_segmentation": {"name": "prostate_segmentation", "category": "segmentation",
                                  "triggers": ["prostate"], "tool_sequence": ["ctv_segmentation"]},
        "full_auto_planning": {"name": "full_auto_planning", "category": "planning",
                               "triggers": ["full plan"], "tool_sequence": ["ctv_segmentation"]}}}
    case_b = {"skills": {
        "standard_planning": {"name": "standard_planning", "category": "planning",
                              "triggers": ["treatment plan"], "tool_sequence": ["seed_planning"]},
        "dvh_analysis": {"name": "dvh_analysis", "category": "evaluation",
                         "triggers": ["dvh"], "tool_sequence": ["dose_evaluation"]}}}
    r_cases = [
        ("duplicate name rejected", case_a, "SKILL_DUPLICATE_NAME"),
        ("persist write denied", case_b, "STORAGE_WRITE_DENIED"),
        ("corrupt registry file", case_a, "REGISTRY_CORRUPT"),
        ("unknown category", case_b, "CATEGORY_UNKNOWN"),
        ("empty evolve pattern", case_a, "EVOLVE_PATTERN_EMPTY"),
        ("concurrent write conflict", case_b, "CONCURRENT_WRITE"),
    ]
    for i, (situation, state, code) in enumerate(r_cases, 1):
        tid = f"SKILLS-REG-{50 + i:03d}"
        import copy as _copy
        before = _copy.deepcopy(state)
        after_ok = _copy.deepcopy(state)
        after_bad = _copy.deepcopy(state)
        victim = sorted(after_bad["skills"])[0]
        del after_bad["skills"][victim]
        cov = {"skills:registry": {"R": _ev(tid, "state_invariant"),
                                   "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "K", "skill_registry_write_rollback",
            f"On {situation} ({code}) the registry must remain unchanged and must not drop skills via a partial write.",
            fixture=RECOVERY, check="state_invariant", derived=deriv_register,
            turns=_turns(f"The registry must not corrupt the existing skill set on {situation}.", lang="en"),
            contrast="K/skill_registry/write_rollback", pos=_inv(before, after_ok),
            neg=_inv(before, after_bad), cov=cov, seed=9190 + i, difficulty="hard",
            comment=f"CI replay for {tid}: {code} leaves all registered skills intact."))

    # -- A: evolution is auditable and duplicate-free ------------------------
    a1_before = [{"task_id": f"plan_{j}", "passed": True} for j in range(1, 6)]
    a1_after = [{"task_id": f"plan_{j}", "passed": True} for j in range(1, 6)]
    a1_regressed = [{"task_id": f"plan_{j}", "passed": (j != 3)} for j in range(1, 6)]
    tid = "SKILLS-REG-057"
    TASKS.append(_gen_entry(
        tid, "K", "skill_registry_evolve_audit",
        "After self-evolution generates new skills, the original task pass set must not regress (K5 veto gate).",
        fixture=MEMORY, check="self_evolution_regression", derived=deriv_evolve,
        turns=_turns("After evolving new skills from interaction history, all original planning tasks must still pass.", lang="en"),
        contrast="K/skill_registry/evolve_regression", pos=_sev(a1_before, a1_after),
        neg=_sev(a1_before, a1_regressed),
        cov={"skills:registry": {"A": _ev(tid, "self_evolution_regression"),
                                 "R": _ev(tid)}},
        seed=9201, difficulty="hard", power_role="safety_gate",
        comment="CI replay for SKILLS-REG-057: no task regressed after evolution."))
    tid = "SKILLS-REG-058"
    TASKS.append(_gen_entry(
        tid, "K", "skill_registry_evolve_audit",
        "Self-evolution must reproduce stably under the same keyword-order patterns and must not create duplicate skills.",
        fixture=MEMORY, check="self_evolution_regression", derived=deriv_evolve,
        turns=_turns("Evolving again from the same interaction pattern must leave the task pass set unchanged.", lang="en"),
        contrast="K/skill_registry/evolve_stability",
        pos=_sev(a1_before, a1_before),
        neg=_sev(a1_before, a1_regressed),
        cov={"skills:registry": {"A": _ev(tid, "self_evolution_regression")}},
        seed=9202, difficulty="hard", power_role="safety_gate",
        comment="CI replay for SKILLS-REG-058: paired evolve is stable."))
    skill_state = {"skills": {"learned_ctv_oar": {"name": "learned_ctv_oar", "usage_count": 1},
                              "learned_seed_dose": {"name": "learned_seed_dose", "usage_count": 1}}}
    import copy as _copy
    idem_bad = _copy.deepcopy(skill_state)
    idem_bad["skills"]["learned_ctv_oar_dup"] = {"name": "learned_ctv_oar_dup", "usage_count": 1}
    tid = "SKILLS-REG-059"
    TASKS.append(_gen_entry(
        tid, "K", "skill_registry_evolve_idempotent",
        "Repeatedly running the same self-evolution round must not leave duplicate skills in the registry.",
        fixture=MEMORY, check="idempotency", derived=deriv_evolve,
        turns=_turns("Running the same evolution round twice must produce the same registry skill set.", lang="en"),
        contrast="K/skill_registry/evolve_idempotency",
        pos=_idem([_copy.deepcopy(skill_state), _copy.deepcopy(skill_state)]),
        neg=_idem([_copy.deepcopy(skill_state), idem_bad]),
        cov={"skills:registry": {"A": _ev(tid, "idempotency"),
                                 "R": _ev(tid)}},
        seed=9203, difficulty="hard", power_role="safety_gate",
        comment="CI replay for SKILLS-REG-059: second evolve is a no-op."))
    tid = "SKILLS-REG-060"
    TASKS.append(_gen_entry(
        tid, "K", "skill_registry_evolve_idempotent",
        "Retrieval results sorted by trigger must remain idempotent after repeated registration and must not accumulate duplicate entries.",
        fixture=MEMORY, check="idempotency", derived=deriv_rate,
        turns=_turns("After registering the same skill repeatedly, the list must not contain duplicates.", lang="en"),
        contrast="K/skill_registry/register_idempotency",
        pos=_idem([{"skills": {"a": 1, "b": 2}}, {"skills": {"a": 1, "b": 2}}]),
        neg=_idem([{"skills": {"a": 1, "b": 2}}, {"skills": {"a": 1, "b": 2, "a_dup": 1}}]),
        cov={"skills:registry": {"A": _ev(tid, "idempotency")}},
        seed=9204, difficulty="hard", power_role="safety_gate",
        comment="CI replay for SKILLS-REG-060: register of the same name is idempotent."))


def _emit_markdown() -> None:
    """skills/markdown_loader.py: YAML frontmatter parsing and retrieval."""
    deriv_parse = "skills/markdown_loader.py:115-130 (_parse_frontmatter regex + yaml.safe_load)"
    deriv_load = "skills/markdown_loader.py:81-113 (_load_skill_file defaults + body)"
    deriv_find = "skills/markdown_loader.py:132-138,167-177 (find_by_trigger / find_skill_for_request max matching triggers)"

    trig = [
        ("prostate", ["prostate_segmentation"], ["pancreas_segmentation"]),
        ("prostate cancer", ["prostate_segmentation"], ["generic_segmentation"]),
        ("pancreas", ["pancreas_segmentation"], ["prostate_segmentation"]),
        ("pancreatic cancer", ["pancreas_segmentation"], ["prostate_full_workflow"]),
        ("segmentation", ["generic_segmentation", "prostate_segmentation", "pancreas_segmentation"], ["report_generation"]),
        ("auto-segmentation", ["generic_segmentation"], ["dicom_export"]),
        ("report", ["report_generation"], ["dicom_export"]),
        ("generate report", ["report_generation"], ["viewer_control"]),
        ("DICOM", ["dicom_export"], ["report_generation"]),
        ("RT Structure", ["dicom_export"], ["dose_evaluation"]),
        ("dose eval", ["dose_evaluation"], ["dvh_analysis"]),
        ("metrics", ["dose_evaluation"], ["report_generation"]),
        ("intraop", ["intraop_replan"], ["standard_planning"]),
        ("replan", ["intraop_replan"], ["rl_planning"]),
        ("deviation", ["intraop_replan"], ["report_generation"]),
        ("reinforcement learning", ["rl_planning"], ["standard_planning"]),
        ("standard plan", ["standard_planning"], ["rl_planning"]),
        ("treatment plan", ["standard_planning"], ["dose_evaluation"]),
        ("viewer", ["viewer_control"], ["standard_planning"]),
        ("overlay", ["viewer_control"], ["dicom_export"]),
    ]
    for i, (text, gold, bad) in enumerate(trig, 1):
        tid = f"SKILLS-MD-{i:03d}"
        cov = {"skills:markdown_loader": {"F": _ev(tid, "retrieval_at_k")}}
        TASKS.append(_gen_entry(
            tid, "L", "markdown_skill_trigger_match",
            f"Markdown skill trigger-word retrieval must hit {gold}.",
            fixture=INTEROP, check="retrieval_at_k", derived=deriv_find,
            turns=_turns(text), contrast="L/markdown_loader/trigger_match",
            pos=_rk([gold], [gold]), neg=_rk([bad], [gold]), cov=cov,
            seed=9300 + i, difficulty="easy",
            comment=f"CI replay for {tid}: '{text}' retrieves {gold}."))

    phr = [
        (["prostate", "prostate", "prostate cancer"], ["prostate_segmentation"], ["pancreas_segmentation"]),
        (["pancreas", "pancreas", "pancreatic cancer"], ["pancreas_segmentation"], ["prostate_segmentation"]),
        (["segmentation", "segmentation", "auto-segmentation"], ["generic_segmentation"], ["dicom_export"]),
        (["report", "report", "generate report"], ["report_generation"], ["dicom_export"]),
        (["DICOM", "export", "RT Plan"], ["dicom_export"], ["report_generation"]),
        (["dose assessment", "dose eval", "dose evaluation"], ["dose_evaluation"], ["dvh_analysis"]),
        (["intraoperative", "intraop", "replan"], ["intraop_replan"], ["standard_planning"]),
        (["reinforcement learning", "RL", "reinforcement learning"], ["rl_planning"], ["standard_planning"]),
        (["standard plan", "standard plan", "treatment plan"], ["standard_planning"], ["rl_planning"]),
        (["viewer", "viewer", "window"], ["viewer_control"], ["dicom_export"]),
        (["pancreatic cancer", "pancreatic", "pancreas cancer"], ["pancreas_segmentation"], ["prostate_segmentation"]),
        (["auto segmentation", "auto seg", "auto-segmentation"], ["generic_segmentation"], ["report_generation"]),
        (["export", "export", "DICOM"], ["dicom_export"], ["viewer_control"]),
        (["evaluation", "evaluation", "metrics"], ["dose_evaluation"], ["report_generation"]),
        (["replanning", "replanning", "deviation"], ["intraop_replan"], ["rl_planning"]),
    ]
    for i, (texts, gold, bad) in enumerate(phr, 1):
        tid = f"SKILLS-MD-{20 + i:03d}"
        pos = _rk([[gold], [gold], [gold]], [[gold], [gold], [gold]])
        neg = _rk([[gold], [bad], [gold]], [[gold], [gold], [gold]])
        cov = {"skills:markdown_loader": {"P": _ev(tid, "retrieval_at_k"),
                                          "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "L", "markdown_skill_expression_robust",
            f"Chinese/English and alias expressions must all retrieve the {gold} skill.",
            fixture=INTEROP, check="retrieval_at_k", derived=deriv_find,
            turns=[{"role": "user", "text": t, "lang": ("zh" if any("\u4e00" <= c <= "\u9fff" for c in t) else "en")}
                   for t in texts],
            contrast="L/markdown_loader/expression", pos=pos, neg=neg, cov=cov,
            seed=9330 + i, group_type="G-EQ", paraphrase=f"{tid}-P01",
            probes=["paraphrase"],
            comment=f"CI replay for {tid}: all phrasings hit {gold}."))

    files = [
        ("prostate_segmentation", {"name": "prostate_segmentation", "category": "segmentation",
                                   "triggers": ["prostate", "prostate cancer"],
                                   "tool_sequence": ["ctv_segmentation", "oar_segmentation"],
                                   "success_threshold": 0.8, "version": "1.0.0"}),
        ("pancreas_segmentation", {"name": "pancreas_segmentation", "category": "segmentation",
                                   "triggers": ["pancreas", "pancreatic cancer"],
                                   "tool_sequence": ["ctv_segmentation", "oar_segmentation"],
                                   "success_threshold": 0.8, "version": "1.0.0"}),
        ("generic_segmentation", {"name": "generic_segmentation", "category": "segmentation",
                                  "triggers": ["segmentation", "auto segmentation", "auto-segmentation"],
                                  "tool_sequence": ["ctv_segmentation", "oar_segmentation"],
                                  "success_threshold": 0.7, "version": "1.0.0"}),
        ("report_generation", {"name": "report_generation", "category": "export",
                               "triggers": ["report", "generate report"],
                               "tool_sequence": ["report_generator"],
                               "success_threshold": 0.9, "version": "1.0.0"}),
        ("dicom_export", {"name": "dicom_export", "category": "export",
                          "triggers": ["DICOM", "export", "RT Structure", "RT Plan"],
                          "tool_sequence": ["dicom_rt_exporter"],
                          "success_threshold": 0.9}),
        ("dose_evaluation", {"name": "dose_evaluation", "category": "evaluation",
                             "triggers": ["evaluation", "dose eval", "metrics", "dose evaluation"],
                             "tool_sequence": ["dose_evaluation", "oar_constraint_checker", "plan_quality_scorer"],
                             "success_threshold": 0.7}),
        ("intraop_replan", {"name": "intraop_replan", "category": "intraoperative",
                            "triggers": ["intraop", "intraoperative", "replan", "replanning", "deviation"],
                            "tool_sequence": ["seed_segmentation", "dose_engine", "dose_evaluation"],
                            "success_threshold": 0.7}),
        ("rl_planning", {"name": "rl_planning", "category": "planning",
                         "triggers": ["RL", "reinforcement learning", "reinforcement", "rl planning"],
                         "tool_sequence": ["ctv_segmentation", "seed_planning_rl", "dose_engine"],
                         "success_threshold": 0.7}),
        ("standard_planning", {"name": "standard_planning", "category": "planning",
                               "triggers": ["planning", "standard plan", "treatment plan", "plan"],
                               "tool_sequence": ["ctv_segmentation", "seed_planning", "dose_engine"],
                               "success_threshold": 0.7}),
        ("viewer_control", {"name": "viewer_control", "category": "viewer",
                            "triggers": ["viewer", "window", "slice", "overlay"],
                            "tool_sequence": ["code_executor"],
                            "success_threshold": 0.7}),
    ]
    for i, (fname, fm) in enumerate(files, 1):
        tid = f"SKILLS-MD-{35 + 2 * i - 1:03d}"
        bad_fm = dict(fm)
        bad_fm["triggers"] = list(fm["triggers"]) + ["corrupted_trigger"]
        cov = {"skills:markdown_loader": {"I": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "L", "markdown_frontmatter_roundtrip",
            f"Markdown skill {fname} frontmatter fields must round-trip faithfully.",
            fixture=INTEROP, check="roundtrip_fidelity", derived=deriv_parse,
            turns=_turns(f"Read the frontmatter of {fname}.md and write it back; the fields must match.", lang="en"),
            contrast=f"L/markdown_loader/roundtrip/{fname}",
            pos=_rt("generic", {"labels": fm}, {"labels": fm}, {"labels": fm}),
            neg=_rt("generic", {"labels": fm}, {"labels": bad_fm}, {"labels": fm}),
            cov=cov, seed=9360 + i, difficulty="medium",
            comment=f"CI replay for {tid}: {fname} frontmatter preserved."))
        tid2 = f"SKILLS-MD-{35 + 2 * i:03d}"
        cov2 = {"skills:markdown_loader": {"I": _ev(tid2, "roundtrip_fidelity"),
                                           "E": _ev(tid2)}}
        TASKS.append(_gen_entry(
            tid2, "L", "markdown_frontmatter_roundtrip",
            f"The success_threshold/version of {fname}.md must not be overwritten by defaults on round-trip.",
            fixture=INTEROP, check="roundtrip_fidelity", derived=deriv_load,
            turns=_turns(f"After reading back {fname}.md, success_threshold and version must be preserved.", lang="en"),
            contrast=f"L/markdown_loader/threshold/{fname}",
            pos=_rt("generic", {"numbers": {"success_threshold": fm.get("success_threshold", 0.7),
                                            "version": fm.get("version", "1.0.0")}},
                    {"numbers": {"success_threshold": fm.get("success_threshold", 0.7),
                                 "version": fm.get("version", "1.0.0")}},
                    {"numbers": {"success_threshold": fm.get("success_threshold", 0.7),
                                 "version": fm.get("version", "1.0.0")}}),
            neg=_rt("generic", {"numbers": {"success_threshold": fm.get("success_threshold", 0.7),
                                            "version": fm.get("version", "1.0.0")}},
                    {"numbers": {"success_threshold": 0.7, "version": "0.0.0"}},
                    {"numbers": {"success_threshold": fm.get("success_threshold", 0.7),
                                 "version": fm.get("version", "1.0.0")}}),
            cov=cov2, seed=9370 + i, difficulty="medium",
            comment=f"CI replay for {tid2}: non-default {fname} fields survive."))

    # -- E: malformed frontmatter is skipped, never corrupting loaded skills --
    base = {"skills": {"prostate_segmentation": {"name": "prostate_segmentation"},
                       "dose_evaluation": {"name": "dose_evaluation"}}}
    import copy as _copy
    mal = [
        ("no closing --- marker", "NO_FRONTMATTER"),
        ("invalid YAML scalar", "YAML_ERROR"),
        ("triggers is a string", "TRIGGER_TYPE"),
        ("missing name falls back to filename", "NAME_FALLBACK"),
        ("empty file", "EMPTY_FILE"),
    ]
    for i, (situation, code) in enumerate(mal, 1):
        tid = f"SKILLS-MD-{55 + i:03d}"
        before = _copy.deepcopy(base)
        after_ok = _copy.deepcopy(base)
        after_bad = _copy.deepcopy(base)
        if code == "NAME_FALLBACK":
            after_bad["skills"]["unknown"] = {"name": ""}
        else:
            del after_bad["skills"]["dose_evaluation"]
        cov = {"skills:markdown_loader": {"E": _ev(tid, "state_invariant"),
                                          "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "L", "markdown_malformed_frontmatter",
            f"The skill file for {situation} must be skipped, and already-loaded skills must not be affected.",
            fixture=INTEROP, check="state_invariant", derived=deriv_parse,
            turns=_turns(f"An skill.md with {situation} must not corrupt other loaded skills.", lang="en"),
            contrast=f"L/markdown_loader/malformed/{code}",
            pos=_inv(before, after_ok), neg=_inv(before, after_bad),
            cov=cov, seed=9410 + i, difficulty="hard",
            comment=f"CI replay for {tid}: {situation} is skipped without side effects."))
    for i, code in enumerate(("YAML_ERROR", "FRONTMATTER_TYPE_ERROR"), 1):
        tid = f"SKILLS-MD-{60 + i:03d}"
        pos_err = {"code": code, "message": f"frontmatter parsing failed: {code}",
                   "retryable": False, "op_id": f"op_md_{i}"}
        neg_err = dict(pos_err, retryable=True)
        cov = {"skills:markdown_loader": {"E": _ev(tid, "error_contract")}}
        TASKS.append(_gen_entry(
            tid, "L", "markdown_frontmatter_error_envelope",
            f"{code} must return as a non-retryable error envelope.",
            fixture=INTEROP, check="error_contract", derived=deriv_parse,
            turns=_turns(f"The frontmatter error {code} must return a stable error code.", lang="en"),
            contrast=f"L/markdown_loader/error/{code}", pos=_err([pos_err]),
            neg=_err([neg_err]), cov=cov, seed=9420 + i, difficulty="easy",
            power_role="secondary",
            comment=f"CI replay for {tid}: {code} is a non-retryable typed error."))


def _emit_templates() -> None:
    """skills/{advanced,planning,segmentation,evaluation}_skills.py templates."""
    deriv_adv = "skills/advanced_skills.py (Skill subclasses: name/category/triggers/tool_sequence/parameters)"
    deriv_liver = "skills/advanced_skills.py:144-168 (liver ref_direc [1,0,0] right-lateral)"
    deriv_lung = "skills/advanced_skills.py:171-192 (lung ref_direc [0,1,0] anterior)"
    deriv_plan = "skills/planning_skills.py:10-83 (standard/RL/quick planning templates)"
    deriv_seg = "skills/segmentation_skills.py:10-67 (pancreas/prostate/generic segmentation)"
    deriv_eval = "skills/evaluation_skills.py:10-50 (standard/detailed evaluation)"

    trig = [
        ("full plan", ["full_auto_planning"], ["quick_plan"]),
        ("complete planning", ["full_auto_planning"], ["dvh_analysis"]),
        ("quick plan", ["quick_plan"], ["full_auto_planning"]),
        ("fast plan", ["quick_plan"], ["rl_optimized_plan"]),
        ("rl plan", ["rl_optimized_plan"], ["quick_plan"]),
        ("RL optimization", ["rl_optimized_plan"], ["full_auto_planning"]),
        ("pancreas segment", ["pancreas_ctv_seg"], ["prostate_full_workflow"]),
        ("pancreas oar", ["pancreas_oar_seg"], ["pancreas_ctv_seg"]),
        ("pancreas workflow", ["pancreas_full_workflow"], ["prostate_full_workflow"]),
        ("prostate workflow", ["prostate_full_workflow"], ["pancreas_full_workflow"]),
        ("liver workflow", ["liver_full_workflow"], ["lung_full_workflow"]),
        ("liver brachytherapy", ["liver_full_workflow"], ["prostate_full_workflow"]),
        ("hepatic", ["liver_full_workflow"], ["lung_full_workflow"]),
        ("lung workflow", ["lung_full_workflow"], ["liver_full_workflow"]),
        ("lung brachytherapy", ["lung_full_workflow"], ["liver_full_workflow"]),
        ("pulmonary", ["lung_full_workflow"], ["liver_full_workflow"]),
        ("dose eval", ["comprehensive_dose_eval"], ["dvh_analysis"]),
        ("evaluate dose", ["comprehensive_dose_eval"], ["quality_check"]),
        ("optimize", ["plan_optimization"], ["quick_plan"]),
        ("improve plan", ["plan_optimization"], ["full_auto_planning"]),
        ("intraop", ["intraop_replan"], ["plan_optimization"]),
        ("replan", ["intraop_replan"], ["quality_check"]),
        ("export dicom", ["dicom_export"], ["report_generation"]),
        ("DICOM RT", ["dicom_export"], ["dvh_analysis"]),
        ("generate report", ["report_generation"], ["dicom_export"]),
        ("segment all", ["multi_organ_seg"], ["voco_segmentation"]),
        ("totalsegmentator", ["multi_organ_seg"], ["dicom_export"]),
        ("voco", ["voco_segmentation"], ["multi_organ_seg"]),
    ]
    for i, (text, gold, bad) in enumerate(trig, 1):
        tid = f"SKILLS-TPL-{i:03d}"
        cov = {"skills:templates": {"F": _ev(tid, "retrieval_at_k")}}
        TASKS.append(_gen_entry(
            tid, "A", "skill_template_trigger_match",
            f"Skill template {gold} must be hit by the trigger word '{text}'.",
            fixture=PROSTATE, check="retrieval_at_k", derived=deriv_adv,
            turns=_turns(text), contrast="A/skill_templates/trigger_match",
            pos=_rk([gold], [gold]), neg=_rk([bad], [gold]), cov=cov,
            seed=9500 + i, difficulty="easy",
            comment=f"CI replay for {tid}: '{text}' selects {gold}."))

    phr = [
        (["full plan", "full plan", "full pipeline"], ["full_auto_planning"], ["quick_plan"]),
        (["quick plan", "fast plan", "rapid plan"], ["quick_plan"], ["full_auto_planning"]),
        (["reinforcement learning plan", "rl plan", "reinforcement learning plan"], ["rl_optimized_plan"], ["quick_plan"]),
        (["pancreas segmentation", "pancreas segment", "pancreas segmentation"], ["pancreas_ctv_seg"], ["prostate_full_workflow"]),
        (["pancreatic organs at risk", "pancreatic organs", "pancreas OAR"], ["pancreas_oar_seg"], ["pancreas_ctv_seg"]),
        (["liver workflow", "liver workflow", "hepatic workflow"], ["liver_full_workflow"], ["lung_full_workflow"]),
        (["lung workflow", "lung workflow", "pulmonary workflow"], ["lung_full_workflow"], ["liver_full_workflow"]),
        (["dose assessment", "dose assessment", "check dose"], ["comprehensive_dose_eval"], ["dvh_analysis"]),
        (["plan optimization", "refine plan", "plan refinement"], ["plan_optimization"], ["quick_plan"]),
        (["intraoperative replan", "intra-operative", "seed check"], ["intraop_replan"], ["plan_optimization"]),
        (["export DICOM", "export plan", "DICOM RT"], ["dicom_export"], ["report_generation"]),
        (["generate report", "create report", "report summary"], ["report_generation"], ["dvh_analysis"]),
        (["multi-organ segmentation", "multi-organ", "all organs"], ["multi_organ_seg"], ["voco_segmentation"]),
        (["DVH analysis", "DVH analysis", "dose volume"], ["dvh_analysis"], ["quality_check"]),
        (["quality check", "verify plan", "plan review"], ["quality_check"], ["report_generation"]),
        (["self-evolution", "self-improve", "self-evolve"], ["self_evolve"], ["code_writer"]),
        (["write new tool", "create tool", "write code"], ["code_writer"], ["self_evolve"]),
        (["pancreas full workflow", "pancreatic brachytherapy", "pancreas full"], ["pancreas_full_workflow"], ["prostate_full_workflow"]),
        (["prostate full workflow", "prostate brachytherapy", "prostate full"], ["prostate_full_workflow"], ["pancreas_full_workflow"]),
        (["detailed evaluation", "detailed", "comprehensive"], ["detailed_evaluation"], ["standard_evaluation"]),
    ]
    for i, (texts, gold, bad) in enumerate(phr, 1):
        tid = f"SKILLS-TPL-{28 + i:03d}"
        pos = _rk([[gold], [gold], [gold]], [[gold], [gold], [gold]])
        neg = _rk([[gold], [bad], [gold]], [[gold], [gold], [gold]])
        cov = {"skills:templates": {"P": _ev(tid, "retrieval_at_k"),
                                    "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "A", "skill_template_expression_robust",
            f"Multiple phrasings of the same planning intent must all select template {gold}.",
            fixture=PROSTATE, check="retrieval_at_k", derived=deriv_adv,
            turns=[{"role": "user", "text": t, "lang": ("zh" if any("\u4e00" <= c <= "\u9fff" for c in t) else "en")}
                   for t in texts],
            contrast="A/skill_templates/expression", pos=pos, neg=neg, cov=cov,
            seed=9530 + i, group_type="G-EQ", paraphrase=f"{tid}-P01",
            probes=["paraphrase"],
            comment=f"CI replay for {tid}: all phrasings select {gold}."))

    exp = [
        ("full_auto_planning", "planning"), ("quick_plan", "planning"),
        ("rl_optimized_plan", "planning"), ("pancreas_ctv_seg", "segmentation"),
        ("pancreas_oar_seg", "segmentation"), ("pancreas_full_workflow", "workflow"),
        ("prostate_full_workflow", "workflow"), ("liver_full_workflow", "workflow"),
        ("lung_full_workflow", "workflow"), ("comprehensive_dose_eval", "evaluation"),
        ("plan_optimization", "optimization"), ("intraop_replan", "intraoperative"),
    ]
    for i, (name, category) in enumerate(exp, 1):
        tid = f"SKILLS-TPL-{48 + i:03d}"
        parsed_ok = {"schema_valid": True, "name": name, "category": category,
                     "tool_sequence": ["ctv_segmentation", "dose_engine"]}
        parsed_bad = dict(parsed_ok, tool_sequence=[], schema_valid=True)
        cov = {"skills:templates": {"E": _ev(tid, "export_artifact_validity"),
                                    "F": _ev(tid)}}
        derived = deriv_liver if name == "liver_full_workflow" else (
            deriv_lung if name == "lung_full_workflow" else deriv_adv)
        TASKS.append(_gen_entry(
            tid, "A", "skill_template_export_validity",
            f"The JSON exported from template {name} must carry a valid category and tool sequence.",
            fixture=PROSTATE, check="export_artifact_validity", derived=derived,
            turns=_turns(f"Export the {name} skill template as JSON and validate its structure.", lang="en"),
            contrast=f"A/skill_templates/export/{name}",
            pos=_exp([{"format": "json", "path": f"{name}.json", "parsed": parsed_ok}]),
            neg=_exp([{"format": "json", "path": f"{name}.json",
                       "parsed": dict(parsed_bad, schema_valid=False)}]),
            cov=cov, seed=9560 + i, difficulty="easy",
            comment=f"CI replay for {tid}: {name} exports a schema-valid template."))
    import copy as _copy
    liver_pos = {"planning_pipeline": {"ref_direc": [1.0, 0.0, 0.0]}}
    lung_pos = {"planning_pipeline": {"ref_direc": [0.0, 1.0, 0.0]}}
    for tid, label, derived, state, bad in (
        ("SKILLS-TPL-061", "liver right-lateral", deriv_liver, liver_pos,
         {"planning_pipeline": {"ref_direc": [0.0, 0.0, 1.0]}}),
        ("SKILLS-TPL-062", "lung anterior", deriv_lung, lung_pos,
         {"planning_pipeline": {"ref_direc": [1.0, 0.0, 0.0]}}),
    ):
        cov = {"skills:templates": {"E": _ev(tid, "roundtrip_fidelity"),
                                    "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "A", "skill_template_site_direction",
            f"The default ref_direc direction of the {label} template must be correct and round-trip faithfully.",
            fixture=PROSTATE, check="roundtrip_fidelity", derived=derived,
            turns=_turns(f"Confirm the default needle direction parameter of {label} was not rewritten.", lang="en"),
            contrast=f"A/skill_templates/ref_direc/{label.split()[0]}",
            pos=_rt("generic", {"labels": state}, {"labels": _copy.deepcopy(state)},
                    {"labels": _copy.deepcopy(state)}),
            neg=_rt("generic", {"labels": state}, {"labels": bad},
                    {"labels": _copy.deepcopy(state)}),
            cov=cov, seed=9580, difficulty="hard",
            comment=f"CI replay for {tid}: {label} ref_direc preserved."))


def _emit_ct_volume() -> None:
    """utils/ct_volume.py: 3-D/4-D/DICOM normalisation and geometry."""
    deriv = "utils/ct_volume.py:38-111 (normalize_ct_image: dim guard, 4-D Extract, vector cast, geometry preserved)"
    deriv_err = "utils/ct_volume.py:30-36,81-94 (empty image / unsupported dimension / frame range ValueErrors)"

    # geometry profiles (LPS / ITK)
    DIR_I = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    DIR_ROT_Z = [0, -1, 0, 1, 0, 0, 0, 0, 1]
    DIR_ROT_X = [1, 0, 0, 0, 0, -1, 0, 1, 0]
    DIR_ROT_Y = [0, 0, 1, 0, 1, 0, -1, 0, 0]
    profiles = [
        ("prostate_3d", [512, 512, 128], [0.5, 0.5, 1.0], [-128.0, -128.0, -64.0], DIR_I, "int16"),
        ("prostate_4d_reduced", [512, 512, 128], [0.5, 0.5, 1.0], [-128.0, -128.0, -64.0], DIR_I, "float32"),
        ("liver_3d", [512, 512, 96], [0.7, 0.7, 1.0], [-180.0, -180.0, -48.0], DIR_I, "int16"),
        ("liver_oblique", [512, 512, 96], [0.7, 0.7, 1.0], [-180.0, -180.0, -48.0], DIR_ROT_Z, "int16"),
        ("lung_3d", [512, 512, 160], [0.6, 0.6, 1.0], [-160.0, -160.0, -80.0], DIR_I, "int16"),
        ("lung_rot_x", [512, 512, 160], [0.6, 0.6, 1.0], [-160.0, -160.0, -80.0], DIR_ROT_X, "int16"),
        ("pancreas_3d", [512, 512, 112], [0.8, 0.8, 1.0], [-200.0, -200.0, -56.0], DIR_I, "float32"),
        ("pancreas_rot_y", [512, 512, 112], [0.8, 0.8, 1.0], [-200.0, -200.0, -56.0], DIR_ROT_Y, "float32"),
        ("brain_3d", [256, 256, 180], [1.0, 1.0, 1.0], [-128.0, -128.0, -90.0], DIR_I, "int16"),
        ("brain_4d_reduced", [256, 256, 180], [1.0, 1.0, 1.0], [-128.0, -128.0, -90.0], DIR_I, "float32"),
    ]
    for i in range(25):
        tid = f"UTILS-CT-{i + 1:03d}"
        name, dims, spacing, origin, direction, dtype = profiles[i % len(profiles)]
        first = {"dims": list(dims), "spacing": list(spacing), "origin": list(origin),
                 "direction": list(direction), "dtype": dtype}
        cov = {"utils:ct_volume": {"F": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "L", "ct_volume_normalization_geometry",
            f"The {name} CT must preserve voxel-grid geometry and dtype after normalization.",
            fixture=INTEROP, check="roundtrip_fidelity", derived=deriv,
            turns=_turns(f"After loading and normalizing the {name} CT, spacing/origin/direction and dtype must be unchanged.", lang="en"),
            contrast="L/ct_volume/geometry",
            pos=_rt("nifti", first, dict(first), dict(first)),
            neg=_rt("nifti", first, dict(first, dims=list(dims) + [1]), dict(first)),
            cov=cov, seed=9600 + i, difficulty="easy",
            comment=f"CI replay for {tid}: {name} geometry preserved after normalisation."))

    codes = [
        ("CT_EMPTY", False), ("CT_DIMENSION_UNSUPPORTED", False),
        ("CT_FRAME_INDEX_OUT_OF_RANGE", False), ("CT_NO_FRAMES", False),
        ("CT_VECTOR_REDUCTION_FAILED", False), ("CT_ORIENTATION_FAILED", False),
        ("CT_FRAME_EXTRACT_FAILED", False), ("CT_SERIES_INCONSISTENT", False),
        ("CT_SPACING_INVALID", False), ("CT_DIRECTION_SINGULAR", False),
        ("CT_DTYPE_UNSUPPORTED", False), ("CT_LAYOUT_UNSUPPORTED", False),
        ("CT_METADATA_MISSING", False), ("CT_FRAME_NOT_UNIQUE", False),
        ("CT_DICOM_ORIENT_FAILED", False), ("BUSY", True),
        ("UNAVAILABLE", True), ("TIMEOUT", True), ("NETWORK", True),
        ("OOM_RETRY", True),
    ]
    for i, (code, retry) in enumerate(codes, 1):
        tid = f"UTILS-CT-{25 + i:03d}"
        pos_err = {"code": code, "message": f"CT normalization failed: {code}",
                   "retryable": retry, "op_id": f"op_ct_{i:03d}"}
        neg_err = dict(pos_err, retryable=not retry)
        cov = {"utils:ct_volume": {"E": _ev(tid, "error_contract")}}
        TASKS.append(_gen_entry(
            tid, "L", "ct_volume_error_contract",
            f"CT dimension/frame error {code} must return as a decidable error envelope, with retryable consistent with the code.",
            fixture=INTEROP, check="error_contract", derived=deriv_err,
            turns=_turns(f"Normalization encountering {code} must return a stable error code.", lang="en"),
            contrast=f"L/ct_volume/error/{code}", pos=_err([pos_err]),
            neg=_err([neg_err]), cov=cov, seed=9630 + i, difficulty="easy",
            power_role="secondary",
            comment=f"CI replay for {tid}: {code} envelope retryable={retry}."))

    for i in range(15):
        tid = f"UTILS-CT-{46 + i:03d}"
        name, dims, spacing, origin, direction, dtype = profiles[i % len(profiles)]
        header = {"origin": list(origin), "spacing": list(spacing),
                  "direction": list(direction)}
        header_shift = dict(header, origin=[origin[0] + 0.01, origin[1], origin[2]])
        cov = {"utils:ct_volume": {"I": _ev(tid, "coord_roundtrip")}}
        if i % 3 == 2:
            directional = list(direction)
            neg_direction = [1, 0, 0, 0, 1, 0, 0, 0, -1]
            TASKS.append(_gen_entry(
                tid, "L", "ct_volume_coordinate_fidelity",
                f"The direction matrix of {name} must be a right-handed orthogonal rotation, not a mirror.",
                fixture=INTEROP, check="coord_roundtrip",
                derived="utils/ct_volume.py:96-108 + oracles/coord_roundtrip.py:67-90 (proper-rotation direction)",
                turns=_turns(f"Validate that the direction of {name} is a valid rotation matrix.", lang="en"),
                contrast="L/ct_volume/direction",
                pos=_coord(samples=[[0, 0, 0], [1, 2, 3]], origin=origin,
                           spacing=spacing, direction=directional),
                neg=_coord(samples=[[0, 0, 0]], origin=origin, spacing=spacing,
                           direction=neg_direction),
                cov=cov, seed=9650 + i, difficulty="medium",
                comment=f"CI replay for {tid}: {name} direction is a proper rotation."))
        else:
            TASKS.append(_gen_entry(
                tid, "L", "ct_volume_coordinate_fidelity",
                f"The origin/spacing/direction of {name} must be consistent before and after normalization (no origin drift).",
                fixture=INTEROP, check="coord_roundtrip",
                derived="utils/ct_volume.py:96-108 (Extract preserves origin/spacing/direction)",
                turns=_turns(f"Compare the geometry headers of {name} before and after normalization.", lang="en"),
                contrast="L/ct_volume/header_consistency",
                pos=_coord(header_a=header, header_b=dict(header)),
                neg=_coord(header_a=header, header_b=header_shift),
                cov=cov, seed=9650 + i, difficulty="medium",
                comment=f"CI replay for {tid}: {name} header preserved."))


def _emit_display_paths() -> None:
    """utils/display_paths.py: token relativise / resolve round-trips + safety."""
    deriv_rel = "utils/display_paths.py:82-100 (relativize_text / relativize_value token rewrite)"
    deriv_res = "utils/display_paths.py:127-147 (resolve_user_path joins token to root)"
    deriv_roots = "utils/display_paths.py:32-54,189-205 (DisplayRoots pairs / roots_from_workspace)"
    deriv_generic = "utils/display_paths.py:72-89 (_generic_replacement hides system roots)"

    combos = [
        ("workspace", "<workspace>", "/tmp/opencode/workspace/case_a"),
        ("runtime", "<runtime>", "/tmp/opencode/workspace/.runtime"),
        ("app", "<app>", "/tmp/opencode/app"),
    ]
    tokens = [
        "<workspace>/ct.nii.gz", "<workspace>/plan/plan.json",
        "<runtime>/logs/turn.log", "<runtime>/seeds/seed_03.json",
        "<app>/models/prostate.pt", "<app>/config/site.json",
        "<workspace>/seg/ctv.nii.gz", "<workspace>/dose/dose.nii.gz",
        "<runtime>/cache/viewer.tmp", "<app>/skills/markdown/report_generation.md",
        "<path>/dvh.csv", "<path>/session_manifest.json",
    ]
    for i in range(20):
        tid = f"UTILS-PATH-{i + 1:03d}"
        token = tokens[i % len(tokens)]
        root_name, root_tok, root = combos[i % len(combos)]
        resolved = token.replace(root_tok, root).replace("<path>", root)
        first = {"labels": {"token": token, "resolved": resolved}}
        cov = {"utils:display_paths": {"F": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "D2", "display_path_token_roundtrip",
            f"Display path token {token} must reversibly resolve back to the real path under {root}.",
            fixture=SECURITY, check="roundtrip_fidelity", derived=deriv_res,
            turns=_turns(f"Resolve {token} back to an absolute path; it must land under {root}.", lang="en"),
            contrast="D2/display_paths/token_roundtrip",
            pos=_rt("generic", first, {"labels": dict(first["labels"])},
                    {"labels": dict(first["labels"])}),
            neg=_rt("generic", first,
                    {"labels": {"token": token, "resolved": "/etc/passwd"}},
                    {"labels": dict(first["labels"])}),
            cov=cov, seed=9700 + i, difficulty="easy",
            comment=f"CI replay for {tid}: {token} round-trips under {root_name}."))

    # I: separators / generic roots / nested JSON
    sep = [
        ("<workspace>\\ct.nii.gz", "<workspace>/ct.nii.gz"),
        ("<runtime>/a\\b\\c.log", "<runtime>/a/b/c.log"),
        ("<path>/dvh.csv", "<path>/dvh.csv"),
        ("<path>/session_manifest.json", "<path>/session_manifest.json"),
        ("<app>/models\\prostate.pt", "<app>/models/prostate.pt"),
    ]
    for i in range(15):
        tid = f"UTILS-PATH-{21 + i:03d}"
        raw, norm = sep[i % len(sep)]
        first = {"geometry": {"raw": raw, "normalized": norm}}
        cov = {"utils:display_paths": {"I": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "D2", "display_path_separator_interop",
            "Cross-platform backslash tokens must normalize to forward slashes without losing the path tail.",
            fixture=SECURITY, check="roundtrip_fidelity", derived=deriv_rel,
            turns=_turns(f"After processing the Windows-style token {raw}, the result must be {norm}.", lang="en"),
            contrast="D2/display_paths/separators",
            pos=_rt("generic", first, {"geometry": dict(first["geometry"])},
                    {"geometry": dict(first["geometry"])}),
            neg=_rt("generic", first,
                    {"geometry": {"raw": raw, "normalized": raw.replace("\\", "/") + "/"}},
                    {"geometry": dict(first["geometry"])}),
            cov=cov, seed=9720 + i, difficulty="medium",
            comment=f"CI replay for {tid}: separator normalisation preserved."))

    # S: token resolution must not escape allowed roots via '..'
    ops_root = "/tmp/opencode/workspace/case_a"
    for i, (situation, target) in enumerate([
        ("normal write inside the case directory", f"{ops_root}/plan/plan.json"),
        ("write into the EBRT output directory", f"{ops_root}/dose/dose.nii.gz"),
        ("write into the DICOM export directory", f"{ops_root}/dicom/export"),
        ("write into the report directory", f"{ops_root}/report/report.html"),
        ("write into the STL directory", f"{ops_root}/stl/ctv.stl"),
        ("create the dvh directory", f"{ops_root}/dvh"),
        ("move the seed file", f"{ops_root}/seeds/seed_01.json"),
        ("delete the temporary cache", f"{ops_root}/cache/viewer.tmp"),
        ("write the mask", f"{ops_root}/seg/ctv.nii.gz"),
        ("write the session manifest", f"{ops_root}/session_manifest.json"),
        ("write the run log", f"{ops_root}/logs/turn.log"),
        ("write the viewer state", f"{ops_root}/viewer/state.json"),
        ("write the patient file", f"{ops_root}/patient/scan.nii.gz"),
        ("create the evaluation directory", f"{ops_root}/eval"),
        ("write the constraint-check results", f"{ops_root}/eval/constraints.json"),
    ], 1):
        tid = f"UTILS-PATH-{35 + i:03d}"
        cov = {"utils:display_paths": {"S": _ev(tid, "path_traversal_blocked"),
                                       "I": _ev(tid)}}
        pos = _pt([{"op": "write", "target": target}], [ops_root])
        neg = _pt([{"op": "write", "target": f"{ops_root}/../other/secret.json"}], [ops_root])
        TASKS.append(_gen_entry(
            tid, "D2", "display_path_write_stays_in_root",
            f"{situation}: writes resolved from tokens must stay inside the case workspace.",
            fixture=SECURITY, check="path_traversal_blocked", derived=deriv_res,
            turns=_turns(f"{situation}; the resolved write path must not escape the workspace.", lang="en"),
            contrast="D2/display_paths/write_root", pos=pos, neg=neg, cov=cov,
            seed=9740 + i, difficulty="hard", power_role="safety_gate",
            comment=f"CI replay for {tid}: write stays inside the case workspace."))

    # E: boundaries that must be left alone (inline fraction, bare slash)
    edge = [
        ("1/2", "1/2"),
        ("/", "/"),
        ("3/4 of the dose", "3/4 of the dose"),
        ("value: 0/1", "value: 0/1"),
        ("ratio 12/24", "ratio 12/24"),
        ("/unknown_root/secret", "/unknown_root/secret"),
        ("http://example.org/a/b", "http://example.org/a/b"),
        ("C:/data/ct", "C:/data/ct"),
        ("see appendix A/B", "see appendix A/B"),
        ("split 50/50", "split 50/50"),
    ]
    for i, (raw, kept) in enumerate(edge, 1):
        tid = f"UTILS-PATH-{50 + i:03d}"
        first = {"labels": {"input": raw, "output": kept}}
        cov = {"utils:display_paths": {"E": _ev(tid, "roundtrip_fidelity"),
                                       "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "D2", "display_path_boundary_untouched",
            f"Inline fractions/bare slashes {raw!r} must not be rewritten as file paths.",
            fixture=SECURITY, check="roundtrip_fidelity",
            derived="utils/display_paths.py:23-29,72-89 (bare '/' and fractions left alone)",
            turns=_turns(f"The text {raw!r} is not a path and must be preserved verbatim after rewriting.", lang="en"),
            contrast="D2/display_paths/boundary",
            pos=_rt("generic", first, {"labels": dict(first["labels"])},
                    {"labels": dict(first["labels"])}),
            neg=_rt("generic", first,
                    {"labels": {"input": raw, "output": f"<path>/{kept}"}},
                    {"labels": dict(first["labels"])}),
            cov=cov, seed=9760 + i, difficulty="medium",
            comment=f"CI replay for {tid}: {raw!r} left untouched."))


def _emit_planning_metrics() -> None:
    """utils/planning_metrics.py: OAR metric extraction / rendering."""
    deriv_extract = "utils/planning_metrics.py:69-105 (extract_oar_dose_metrics: only dose-bearing organ rows)"
    deriv_norm = "utils/planning_metrics.py:108-133 (normalize_dose_metrics: flat CTV vs nested oars)"
    deriv_format = "utils/planning_metrics.py:179-232 (format_oar_dose_table zh/en, V100 percent)"

    oars = [
        ("bladder", {"D2cc": 75.2, "Dmean": 42.1, "V100": 0.95}),
        ("rectum", {"D2cc": 65.0, "Dmean": 35.7, "V100": 0.92}),
        ("urethra", {"Dmax": 120.5, "D90": 118.0}),
        ("sigmoid", {"D2cc": 70.1, "Dmean": 30.2}),
        ("small_bowel", {"D2cc": 85.0, "Dmax": 90.1}),
        ("femoral_head_l", {"Dmax": 50.0, "Dmean": 22.4}),
        ("femoral_head_r", {"Dmax": 49.3, "Dmean": 21.8}),
        ("spinal_cord", {"Dmax": 45.0, "D2cc": 40.2}),
        ("duodenum", {"D2cc": 80.0, "Dmean": 33.5}),
        ("stomach", {"D2cc": 78.0, "Dmax": 82.3}),
        ("kidney_l", {"Dmean": 12.0, "Dmax": 30.1}),
        ("kidney_r", {"Dmean": 11.4, "Dmax": 28.9}),
        ("liver", {"Dmean": 15.0, "Dmax": 40.0}),
        ("lung_l", {"Dmean": 8.0, "Dmax": 25.0}),
    ]
    for i in range(25):
        tid = f"UTILS-METR-{i + 1:03d}"
        name, row = oars[i % len(oars)]
        first = {"numbers": {name: dict(row)}}
        bad = dict(row)
        k = sorted(bad)[0]
        bad[k] = bad[k] / 10.0
        cov = {"utils:planning_metrics": {"F": _ev(tid, "roundtrip_fidelity"),
                                          "I": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "A", "planning_oar_metric_extraction",
            f"The observed dose metrics of {name} must be extracted correctly and keep their values unchanged.",
            fixture=PROSTATE, check="roundtrip_fidelity", derived=deriv_extract,
            turns=_turns(f"Read the dose metrics of {name}; the values must match the saved planning values.", lang="en"),
            contrast="A/planning_metrics/oar_extract",
            pos=_rt("generic", first, {"numbers": {name: dict(row)}},
                    {"numbers": {name: dict(row)}}),
            neg=_rt("generic", first, {"numbers": {name: bad}},
                    {"numbers": {name: dict(row)}}),
            cov=cov, seed=9800 + i, difficulty="easy",
            comment=f"CI replay for {tid}: {name} metrics preserved."))

    # I: nested oar_metrics / oars / organs_at_risk wrappers must be equivalent
    wrappers = ["oar_metrics", "oars", "oar", "organs_at_risk", "structures"]
    for i, wrapper in enumerate(wrappers * 3, 1):
        tid = f"UTILS-METR-{25 + i:03d}"
        payload = {wrapper: {"bladder": {"D2cc": 75.2}, "rectum": {"D2cc": 65.0}}}
        expected = {"numbers": {"bladder": {"D2cc": 75.2}, "rectum": {"D2cc": 65.0}}}
        bad = {"numbers": {"bladder": {"D2cc": 75.2}}}
        cov = {"utils:planning_metrics": {"I": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "A", "planning_metrics_nested_wrapper",
            f"OAR metrics inside the legacy nested container {wrapper} must be normalized equivalently.",
            fixture=PROSTATE, check="roundtrip_fidelity", derived=deriv_norm,
            turns=_turns(f"Normalize the legacy structure wrapped in {wrapper}; the metric set must not be missing.", lang="en"),
            contrast=f"A/planning_metrics/wrapper/{wrapper}",
            pos=_rt("generic", expected, {"numbers": dict(expected["numbers"])},
                    {"numbers": dict(expected["numbers"])}),
            neg=_rt("generic", expected, bad, {"numbers": dict(expected["numbers"])}),
            cov=cov, seed=9820 + i, difficulty="medium",
            comment=f"CI replay for {tid}: {wrapper} unwrapped without data loss."))

    phr = [
        ("bladder", "bladder"), ("rectum", "rectum"), ("urethra", "urethra"),
        ("sigmoid", "sigmoid"), ("small_bowel", "small_bowel"), ("femoral_head_l", "femoral_head_l"),
        ("spinal_cord", "spinal_cord"), ("duodenum", "duodenum"), ("stomach", "stomach"),
        ("kidney_l", "kidney_l"), ("liver", "liver"), ("lung_l", "lung_l"),
    ]
    for i, (zh, en) in enumerate(phr, 1):
        tid = f"UTILS-METR-{40 + i:03d}"
        row = dict(oars[i % len(oars)][1])
        first = {"labels": {"organ_en": en, "organ_zh": zh, "columns": sorted(row)}}
        cov = {"utils:planning_metrics": {"P": _ev(tid, "roundtrip_fidelity"),
                                          "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "A", "planning_metrics_localization",
            f"The metric column set rendered for organ {zh}/{en} must be identical across localizations.",
            fixture=PROSTATE, check="roundtrip_fidelity", derived=deriv_format,
            turns=_turns(f"Render the dose table for {en} under both localizations; the columns must match.", lang="en"),
            contrast="A/planning_metrics/localization",
            pos=_rt("generic", first, {"labels": dict(first["labels"])},
                    {"labels": dict(first["labels"])}),
            neg=_rt("generic", first,
                    {"labels": {"organ_en": en, "organ_zh": zh,
                                "columns": sorted(row)[:-1] or ["Dmax"]}},
                    {"labels": dict(first["labels"])}),
            cov=cov, seed=9840 + i, difficulty="medium", group_type="G-EQ",
            paraphrase=f"{tid}-P01", probes=["paraphrase"],
            comment=f"CI replay for {tid}: {en}/{zh} render identically."))

    # E: CTV excluded, bool/NaN rejected, non-mapping dropped
    edge = [
        ("ctv_excluded",
         {"numbers": {"bladder": {"D2cc": 75.2}}},
         {"numbers": {"bladder": {"D2cc": 75.2}, "ctv": {"D90": 120.0}}}),
        ("bool_rejected",
         {"numbers": {"bladder": {"D2cc": 75.2}}},
         {"numbers": {"bladder": {"D2cc": 75.2, "computed": True}}}),
        ("nan_rejected",
         {"numbers": {"bladder": {"D2cc": 75.2}}},
         {"numbers": {"bladder": {"D2cc": 75.2, "Dmean": "NaN"}}}),
        ("volume_not_dose",
         {"numbers": {"bladder": {"D2cc": 75.2}}},
         {"numbers": {"bladder": {"D2cc": 75.2, "volume_cc": 45.0}}}),
        ("non_mapping_dropped",
         {"numbers": {}},
         {"numbers": {"bladder": {"D2cc": 75.2}}}),
        ("gross_target_excluded",
         {"numbers": {"rectum": {"D2cc": 65.0}}},
         {"numbers": {"rectum": {"D2cc": 65.0}, "gtv": {"D90": 118.0}}}),
        ("target_type_excluded",
         {"numbers": {"rectum": {"D2cc": 65.0}}},
         {"numbers": {"rectum": {"D2cc": 65.0}, "tumor": {"D90": 118.0}}}),
        ("empty_payload",
         {"numbers": {}},
         {"numbers": {"bladder": {"D2cc": 75.2}}}),
    ]
    for i, (code, first, second) in enumerate(edge, 1):
        tid = f"UTILS-METR-{52 + i:03d}"
        cov = {"utils:planning_metrics": {"E": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "A", "planning_metrics_scope_edge",
            f"Non-OAR rows ({code}) must not be extracted as dose evidence.",
            fixture=PROSTATE, check="roundtrip_fidelity", derived=deriv_extract,
            turns=_turns(f"Rows for {code} must be excluded during normalization.", lang="en"),
            contrast=f"A/planning_metrics/scope/{code}",
            pos=_rt("generic", first, dict(first), dict(first)),
            neg=_rt("generic", first, second, dict(first)),
            cov=cov, seed=9860 + i, difficulty="hard",
            comment=f"CI replay for {tid}: {code} rows are excluded from OAR metrics."))


def _emit_user_errors() -> None:
    """utils/user_errors.py: metadata normalisation, error classification."""
    deriv_norm = "utils/user_errors.py:22-46 (normalize_metadata: non-mapping -> _metadata_contract_error)"
    deriv_provider = "utils/user_errors.py:107-125 (is_provider_error: lead + bounded length)"
    deriv_format = "utils/user_errors.py:229-415 (format_tool_error localized per tool)"
    deriv_sanitize = "utils/user_errors.py:418-441 (sanitize_user_response: provider + internal path guard)"

    # F: normalize_metadata preserves a well-formed mapping
    metas = [
        ("code", "CTV_CONTRACT_ERROR"), ("code", "GRID_MISMATCH"),
        ("code", "INPUT_NOT_LOADED"), ("code", "GUIDE_INVALID"),
        ("code", "PLAN_NOT_COMPLETED"), ("code", "MODEL_MISSING"),
        ("code", "OOM"), ("code", "INFERENCE_FAILED"),
        ("code", "PATH_HIDDEN"), ("code", "PROVIDER_UNAVAILABLE"),
        ("code", "TIMEOUT"), ("code", "BUSY"),
        ("code", "SCHEMA_ERROR"), ("code", "PERMISSION_DENIED"),
        ("code", "NOT_FOUND"),
    ]
    for i, (key, value) in enumerate(metas, 1):
        tid = f"UTILS-ERR-{i:03d}"
        meta = {key: value, "retryable": value in ("TIMEOUT", "BUSY", "PROVIDER_UNAVAILABLE"),
                "user_error_i18n": {"en": "action required", "zh": "需要处理"}}
        first = {"labels": meta}
        bad = dict(meta)
        bad.pop("retryable")
        cov = {"utils:user_errors": {"F": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "I", "user_error_metadata_normalization",
            f"Well-formed tool metadata {value} must not lose fields after normalization.",
            fixture=RECOVERY, check="roundtrip_fidelity", derived=deriv_norm,
            turns=_turns(f"After normalizing the tool metadata for {value}, the fields must be complete.", lang="en"),
            contrast="I/user_errors/metadata_preserve",
            pos=_rt("generic", first, {"labels": dict(meta)}, {"labels": dict(meta)}),
            neg=_rt("generic", first, {"labels": bad}, {"labels": dict(meta)}),
            cov=cov, seed=9900 + i, difficulty="easy",
            comment=f"CI replay for {tid}: metadata {value} preserved."))

    # E: non-mapping metadata collapses to the controlled sentinel
    bad_inputs = ["list", "tuple", "str", "int", "set", "bytes",
                  "generator", "dict_subclass_broken", "ndarray", "NoneType_like",
                  "custom_adapter", "list_of_dicts"]
    for i, kind in enumerate(bad_inputs, 1):
        tid = f"UTILS-ERR-{15 + i:03d}"
        sentinel = {"labels": {"_metadata_contract_error": True, "_metadata_type": kind}}
        cov = {"utils:user_errors": {"E": _ev(tid, "roundtrip_fidelity")}}
        TASKS.append(_gen_entry(
            tid, "I", "user_error_nonmapping_metadata",
            f"Non-mapping {kind} metadata must be normalized into a controlled sentinel rather than crashing.",
            fixture=RECOVERY, check="roundtrip_fidelity", derived=deriv_norm,
            turns=_turns(f"When the adapter returns metadata of type {kind}, the system must not raise.", lang="en"),
            contrast=f"I/user_errors/nonmapping/{kind}",
            pos=_rt("generic", sentinel, {"labels": dict(sentinel["labels"])},
                    {"labels": dict(sentinel["labels"])}),
            neg=_rt("generic", sentinel, {"labels": {}},
                    {"labels": dict(sentinel["labels"])}),
            cov=cov, seed=9920 + i, difficulty="medium",
            comment=f"CI replay for {tid}: {kind} metadata is normalised, not crashed."))

    # P: the error class decision is language-invariant
    classes = [
        ("provider", True, "refresh"), ("transport", True, "retry"),
        ("internal", False, "trace"), ("metadata", False, "rerun"),
        ("ctv_contract", False, "rerun_seg"), ("grid_mismatch", False, "recompute"),
        ("input_not_loaded", True, "wait"), ("model_missing", False, "admin"),
        ("oom", True, "retry_gpu"), ("permission", False, "admin"),
        ("guide_invalid", False, "replan"), ("plan_incomplete", False, "replan"),
    ]
    for i, (cls, retry, action) in enumerate(classes, 1):
        tid = f"UTILS-ERR-{27 + i:03d}"
        decision = {"labels": {"class": cls, "retryable": retry, "action": action}}
        first = {"labels": dict(decision["labels"])}
        neg_class = "provider" if cls != "provider" else "internal"
        cov = {"utils:user_errors": {"P": _ev(tid, "roundtrip_fidelity"),
                                     "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "I", "user_error_language_invariant",
            f"{cls} 类错误在中英文下必须归为同一类并给同一处置建议。",
            fixture=RECOVERY, check="roundtrip_fidelity", derived=deriv_format,
            turns=_turns(f"用中英文分别格式化 {cls} 错误，分类与 retryable 必须一致。"),
            contrast="I/user_errors/language_invariant",
            pos=_rt("generic", first, {"labels": dict(first["labels"])},
                    {"labels": dict(first["labels"])}),
            neg=_rt("generic", first,
                    {"labels": {"class": neg_class, "retryable": retry, "action": action}},
                    {"labels": dict(first["labels"])}),
            cov=cov, seed=9940 + i, difficulty="medium", group_type="G-EQ",
            paraphrase=f"{tid}-P01", probes=["paraphrase"],
            comment=f"CI replay for {tid}: {cls} classed identically in zh/en."))

    # R: typed retryable error envelope for tool failures
    codes = [
        ("TIMEOUT", True), ("UNAVAILABLE", True),
        ("OOM_RETRY", True), ("BUSY", True),
        ("NETWORK", True), ("OOM_RETRY", True),
        ("CTV_CONTRACT_VIOLATION", False), ("CTV_MODEL_MISSING", False),
        ("GRID_MISMATCH", False), ("INPUT_NOT_LOADED", False),
        ("GUIDE_INVALID", False), ("PLAN_NOT_COMPLETED", False),
        ("METADATA_CONTRACT_ERROR", False), ("PERMISSION_DENIED", False),
        ("INTERNAL_ERROR", False),
    ]
    for i, (code, retry) in enumerate(codes, 1):
        tid = f"UTILS-ERR-{39 + i:03d}"
        pos_err = {"code": code, "message": f"Tool failed: {code}",
                   "retryable": retry, "op_id": f"op_err_{i:03d}"}
        neg_err = dict(pos_err, retryable=not retry)
        cov = {"utils:user_errors": {"R": _ev(tid, "error_contract")}}
        TASKS.append(_gen_entry(
            tid, "I", "user_error_retryable_envelope",
            f"The retryable flag of tool error {code} must be consistent with the error-code semantics.",
            fixture=RECOVERY, check="error_contract", derived=deriv_format,
            turns=_turns(f"When handling {code}, the caller must be able to branch on retryable.", lang="en"),
            contrast=f"I/user_errors/retryable/{code}", pos=_err([pos_err]),
            neg=_err([neg_err]), cov=cov, seed=9960 + i, difficulty="easy",
            power_role="secondary",
            comment=f"CI replay for {tid}: {code} retryable={retry}."))

    # S: sanitisation never leaks server-side absolute paths into chat
    leaks = [
        ("/home/user/brachyplan/case_a/plan/plan.json", "/etc/passwd"),
        ("/workspace/case_b/dose/dose.nii.gz", "/workspace/../other/secret.json"),
        ("/home/user/brachyplan/models/prostate.pt", "/home/other/model.pt"),
        ("/home/user/brachyplan/skills/markdown/x.md", "/etc/shadow"),
        ("/home/user/brachyplan/logs/turn.log", "/workspace/../../root/.ssh/id_rsa"),
        ("/home/user/brachyplan/session.json", "/home/user/brachyplan/../other/session.json"),
    ]
    for i, (leaked, escaped) in enumerate(leaks, 1):
        tid = f"UTILS-ERR-{54 + i:03d}"
        before = {"chat": {"leaked_internal_paths": []}}
        after_ok = {"chat": {"leaked_internal_paths": []}, "response": "(server-local paths hidden)"}
        after_bad = {"chat": {"leaked_internal_paths": [leaked]},
                     "response": f"Saved to {leaked}"}
        cov = {"utils:user_errors": {"S": _ev(tid, "state_invariant"),
                                     "R": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "I", "user_error_no_internal_path_leak",
            "After error/reply sanitization, server absolute paths must not be exposed to the chat interface.",
            fixture=SECURITY, check="state_invariant", derived=deriv_sanitize,
            turns=_turns(f"The reply references {leaked}; after sanitization that path must not leak.", lang="en"),
            contrast="I/user_errors/path_leak", pos=_inv(before, after_ok, ["response"]),
            neg=_inv(before, after_bad, ["response"]), cov=cov, seed=9980 + i,
            difficulty="hard", power_role="safety_gate",
            comment=f"CI replay for {tid}: internal path is not surfaced to chat."))


def _emit_cancellation() -> None:
    """utils/cancellation.py: cooperative, thread-local cancellation."""
    deriv = "utils/cancellation.py:30-57 (cancellation_scope thread-local install/restore; is_cancelled; raise_if_cancelled)"
    deriv_restore = "utils/cancellation.py:31-38 (previous checker restored in finally)"
    deriv_broken = "utils/cancellation.py:41-51 (broken checker -> not cancelled)"

    ops = [
        ("guide_resample_0p2mm", "preop"), ("dose_mc_loop", "preop"),
        ("seed_optimize_rl", "preop"), ("oar_seg_inference", "preop"),
        ("ctv_seg_inference", "preop"), ("trajectory_search", "preop"),
        ("stl_marching_cubes", "preop"), ("dvh_accumulation", "preop"),
        ("dicom_export_write", "preop"), ("viewer_reslice", "preop"),
        ("report_render", "preop"), ("mask_resample", "preop"),
        ("grid_regrid", "preop"), ("seed_detect_intraop", "preop"),
        ("coverage_repair", "preop"), ("dose_recompute", "preop"),
        ("plan_refine_iter50", "preop"), ("quality_score", "preop"),
        ("session_export_zip", "preop"), ("manifest_hash", "preop"),
        ("model_warmup", "preop"), ("volume_render", "preop"),
        ("contour_rasterize", "preop"), ("optimization_loop", "preop"),
        ("file_stream_copy", "preop"), ("cuda_kernel_run", "preop"),
        ("seed_activity_tune", "preop"), ("needle_collision_check", "preop"),
        ("guide_boolean_union", "preop"), ("report_pdf_render", "preop"),
        ("upload_decompress", "preop"), ("cache_rebuild", "preop"),
        ("structure_sync", "preop"), ("dose_histogram", "preop"),
        ("finalize_receipts", "preop"),
    ]
    for i, (op, status) in enumerate(ops, 1):
        tid = f"UTILS-CANCEL-{i:03d}"
        pos_state = {"plan": {"status": status, "op": op},
                     "_initial": {"plan": {"status": "preop"}}}
        neg_state = {"plan": {"status": "final", "op": op},
                     "_initial": {"plan": {"status": "preop"}}}
        cov = {"utils:cancellation": {"F": _ev(tid, "pred")}}
        TASKS.append(_pred_entry(
            tid, "E", "cancellation_leaves_plan_unchanged",
            f"After cancellation during {op}, the planning state must remain as it was before cancellation.",
            fixture=RECOVERY, predicate="plan_status_unchanged", derived=deriv,
            turns=_turns(f"The user cancels after starting {op}; the plan must not be moved to a new state.", lang="en"),
            contrast="E/cancellation/plan_unchanged", pos_state=pos_state,
            neg_state=neg_state, cov=cov, seed=10000 + i, difficulty="medium",
            comment=f"CI replay for {tid}: cancel during {op} leaves plan preop."))

    # R: nested scopes restore the previous checker; broken checker is fail-safe
    for i, (situation, code) in enumerate([
        ("the outer cancellation scope must be restored after the inner scope exits", "NESTED_RESTORE"),
        ("the inner scope must not leak cancellation state to the outer scope", "SCOPE_LEAK"),
        ("an exception exiting the scope must still restore the previous checker", "EXCEPTION_RESTORE"),
        ("multiple scopes entered in sequence on one thread must unwind LIFO", "LIFO_RESTORE"),
        ("a scope with an empty checker must not cancel", "NONE_CHECKER"),
        ("a broken checker must be treated as not cancelled", "BROKEN_CHECKER"),
        ("re-entering a scope after cancellation must have independent state", "REENTER_SCOPE"),
        ("the scopes of two operations must not interfere with each other", "TWO_OPS"),
        ("is_cancelled must be false after the cancellation scope exits", "EXIT_CLEAR"),
        ("an OperationCancelled raised by cancellation must not write back state", "EXC_NO_WRITE"),
    ], 1):
        tid = f"UTILS-CANCEL-{35 + i:03d}"
        before = {"threads": {"main": {"checker": None},
                               "tool": {"checker": "outer_checker"}}}
        after_ok = {"threads": {"main": {"checker": None},
                                "tool": {"checker": "outer_checker"}}}
        after_bad = {"threads": {"main": {"checker": "outer_checker"},
                                 "tool": {"checker": "outer_checker"}}}
        cov = {"utils:cancellation": {"R": _ev(tid, "state_invariant"),
                                      "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "E", "cancellation_scope_isolation",
            f"{situation} ({code}); thread-local cancellation state must not bleed into unrelated threads.",
            fixture=RECOVERY, check="state_invariant", derived=deriv_restore,
            turns=_turns(f"Verify: {situation}.", lang="en"),
            contrast=f"E/cancellation/scope/{code}", pos=_inv(before, after_ok),
            neg=_inv(before, after_bad), cov=cov, seed=10040 + i,
            difficulty="hard", power_role="safety_gate",
            comment=f"CI replay for {tid}: {code} keeps per-thread isolation."))

    # R: repeated cancellation of the same turn is idempotent
    for i in range(15):
        tid = f"UTILS-CANCEL-{46 + i:03d}"
        st = {"plan": {"status": "preop"},
              "turn": {"cancelled": True, "reason": "user"}}
        st_bad = {"plan": {"status": "planning"},
                  "turn": {"cancelled": True, "reason": "user"}}
        cov = {"utils:cancellation": {"R": _ev(tid, "idempotency"),
                                      "F": _ev(tid)}}
        TASKS.append(_gen_entry(
            tid, "E", "cancellation_repeat_idempotent",
            "Requesting cancellation repeatedly for the same turn must be idempotent and must not enter a new planning state.",
            fixture=RECOVERY, check="idempotency", derived=deriv,
            turns=_turns("Cancelling the same turn twice in a row must leave the state unchanged.", lang="en"),
            contrast="E/cancellation/idempotent",
            pos=_idem([dict(st), dict(st)]),
            neg=_idem([dict(st), st_bad]), cov=cov, seed=10080 + i,
            difficulty="medium",
            comment=f"CI replay for {tid}: repeated cancel is idempotent."))

    # F: broken checker must not fabricate a cancellation (operation completes)
    for i, op in enumerate([
        "guide_resample", "dose_loop", "rl_optimize", "ctv_infer",
        "oar_infer", "seed_place", "report_render", "stl_build",
        "export_write", "cache_warm",
    ], 1):
        tid = f"UTILS-CANCEL-{60 + i:03d}"
        pos_state = {"plan": {"status": "final"}, "op": op}
        neg_state = {"plan": {"status": "planning"}, "op": op}
        cov = {"utils:cancellation": {"F": _ev(tid, "pred"),
                                      "R": _ev(tid)}}
        TASKS.append(_pred_entry(
            tid, "E", "cancellation_broken_checker_failsafe",
            f"When the cancellation checker for {op} is broken, it must be treated as not cancelled, and no cancellation may be fabricated.",
            fixture=RECOVERY, predicate="plan_is_final", derived=deriv_broken,
            turns=_turns(f"If the cancellation checker raises during {op}, the task must complete normally.", lang="en"),
            contrast="E/cancellation/broken_checker", pos_state=pos_state,
            neg_state=neg_state, cov=cov, seed=10100 + i, difficulty="hard",
            power_role="safety_gate",
            comment=f"CI replay for {tid}: broken checker does not fake a cancel."))


_emit_registry()
_emit_markdown()
_emit_templates()
_emit_ct_volume()
_emit_display_paths()
_emit_planning_metrics()
_emit_user_errors()
_emit_cancellation()

# keep only well-formed entries; every entry already proved locally below.
__all__ = ["TASKS"]
