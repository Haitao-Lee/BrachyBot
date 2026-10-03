"""Artefact / export / reproducibility checkers (DESIGN §8.3, tracks A7/L/H).

Implements: ``report_sections_complete``, ``report_field_provenance``,
``pdf_parseability``, ``export_artifact_validity``, ``roundtrip_fidelity``,
``semantic_equivalence``, ``replay_hash_artifact``.

N11 separation (do not conflate these four notions):
R-a numerical reproducibility | R-b normalised semantic equivalence |
R-c re-run still passes | R-d a different but equally valid solution.
Byte-identical files are **not** required -- ``dicom_rt_exporter`` mints fresh
``generate_uid()`` and ``datetime.now()`` per export, so hashes always differ.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import ConstraintClass, Oracle, OracleResult, PartialStatus, Violation, register
from .tolerances import values_equal


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@register
class ReportSectionsComplete(Oracle):
    """§6.A7 ``report_sections_complete``: required sections are present."""

    id = "report_sections_complete"
    constraint_class = ConstraintClass.POSTCONDITION

    REQUIRED = ("prescription", "technique", "dosimetry", "constraints", "conclusion")

    def check(
        self,
        report: Dict[str, Any],
        *,
        required: Sequence[str] = REQUIRED,
        at: Optional[str] = None,
    ) -> OracleResult:
        present = {s.get("key"): s for s in (report.get("sections") or []) if isinstance(s, dict)}
        missing = [k for k in required if k not in present or not present[k].get("present")]
        violations = [
            Violation("report_section_missing", f"required section {k!r} absent or empty", at=at)
            for k in missing
        ]
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed,
            score=1.0 - len(missing) / max(len(required), 1),
            violations=violations,
            evidence={"required": list(required), "present": sorted(present), "missing": missing},
            constraint_class=self.constraint_class,
        )


@register
class ReportFieldProvenance(Oracle):
    """§6.A7 ``report_field_provenance``: every numeric field traces to an
    observed computation.

    Shares the evidence-key machinery with ``metric_provenance`` (§9.4 B) so a
    report cannot quote a stale, misattributed or cross-case number.
    """

    id = "report_field_provenance"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        fields: Sequence[Dict[str, Any]],
        ctx: Any,
        trace: Sequence[Dict[str, Any]] = (),
        *,
        at: Optional[str] = None,
    ) -> OracleResult:
        from .metric_provenance import MetricProvenance  # shared checker

        claims = [
            {"metric_name": f.get("metric_name"), "value": f.get("value"),
             "claimed_text": f.get("claimed_text"), "evidence_keys": f.get("evidence_keys")}
            for f in fields or []
        ]
        sub = MetricProvenance().check(claims, trace, ctx, at=at)
        n = len(claims)
        return OracleResult(
            oracle_id=self.id,
            passed=sub.passed and n > 0,
            score=sub.score if n else 0.0,
            violations=list(sub.violations) + ([] if n else [Violation(
                "report_has_no_numeric_fields",
                "a report with no numeric fields cannot be provenance-checked (BA-6 analogue)",
                at=at)]),
            evidence={**sub.evidence, "n_report_fields": n},
            constraint_class=self.constraint_class,
            applicable=n > 0,
            coverage=1.0 if n else 0.0,
            partial_status=PartialStatus.PARTIAL if n == 0 else PartialStatus.COMPLETED,
        )


@register
class PdfParseability(Oracle):
    """§6.A7 / §6.L5 ``pdf_parseability``: the exported PDF is a real document.

    Checks the file header, the EOF marker and page count; optionally that a
    text layer can be extracted (a scanned-only image PDF fails text search).
    """

    id = "pdf_parseability"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        pdf_bytes: Optional[bytes] = None,
        *,
        expected_pages: Optional[int] = None,
        require_text_layer: bool = False,
        extracted_text: Optional[str] = None,
        at: Optional[str] = None,
        parser: Optional[Callable] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        if not pdf_bytes:
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=[Violation("pdf_missing", "no PDF bytes supplied", at=at)],
                constraint_class=self.constraint_class,
            )
        if not pdf_bytes.startswith(b"%PDF-"):
            violations.append(Violation(
                "pdf_bad_header", f"starts with {pdf_bytes[:8]!r}", at=at))
        if b"%%EOF" not in pdf_bytes[-2048:]:
            violations.append(Violation("pdf_missing_eof", "no %%EOF in trailer", at=at))
        try:
            if parser is None:
                try:
                    from pypdf import PdfReader
                except ImportError:
                    from PyPDF2 import PdfReader
                document = PdfReader(io.BytesIO(pdf_bytes), strict=True)
                pages = len(document.pages)
                extracted_text = "\n".join(page.extract_text() or "" for page in document.pages)
            else:
                parsed = parser(pdf_bytes)
                pages, extracted_text = int(parsed["pages"]), parsed.get("text", "")
        except ImportError:
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("pdf_parser_unavailable", "independent PDF parser required")])
        except Exception as exc:
            return OracleResult(oracle_id=self.id, passed=False, score=0,
                                violations=[Violation("pdf_parse_failed", f"independent PDF parse: {type(exc).__name__}")])
        if expected_pages is not None and pages != expected_pages:
            violations.append(Violation(
                "pdf_page_count_mismatch", f"{pages} != {expected_pages}", at=at))
        if pages == 0:
            violations.append(Violation("pdf_has_no_pages", "no /Type /Page found", at=at))
        if require_text_layer and not (extracted_text or "").strip():
            violations.append(Violation(
                "pdf_no_text_layer", "text layer required but extraction is empty", at=at))
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"pages": pages, "nbytes": len(pdf_bytes),
                      "has_text_layer": bool((extracted_text or "").strip())},
            constraint_class=self.constraint_class,
        )


@register
class ExportArtifactValidity(Oracle):
    """§6.A7 ``export_artifact_validity``: exported files parse and satisfy a
    schema-level shape check (NIfTI / STL / JSON / CSV / XLSX)."""

    id = "export_artifact_validity"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        artifacts: Sequence[Dict[str, Any]],
        *,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``artifacts`` items: ``{"format": "nifti|stl|json|csv|xlsx", "path"?, "bytes"?,
        "parsed": {...}}`` where ``parsed`` is what an **independent** parser
        produced (DESIGN §8.6 I3 -- not the exporter reading its own output).
        """
        violations: List[Violation] = []
        per: List[Dict[str, Any]] = []
        for a in artifacts or []:
            fmt = (a.get("format") or "").lower()
            parsed = a.get("parsed")
            entry = {"format": fmt, "ok": True}
            if parsed is None:
                entry["ok"] = False
                violations.append(Violation(
                    "export_unverified",
                    f"{fmt}: no independent parser output (§8.6 I3)",
                    at=at, detail={"path": a.get("path")}))
                per.append(entry)
                continue
            if fmt == "nifti":
                ok = all(k in parsed for k in ("dims", "spacing", "origin", "direction")) \
                    and len(parsed.get("dims") or []) == 3
            elif fmt == "stl":
                ok = bool(parsed.get("watertight")) and parsed.get("volume_mm3") is not None
            elif fmt == "json":
                ok = parsed.get("schema_valid") is True
            elif fmt in ("csv", "xlsx"):
                ok = parsed.get("n_rows", 0) > 0 and bool(parsed.get("header"))
            else:
                ok = False
                violations.append(Violation(
                    "export_unknown_format", f"unhandled format {fmt!r}", at=at))
            entry["ok"] = ok
            if not ok:
                violations.append(Violation(
                    "export_artifact_invalid", f"{fmt}: independent parse failed shape check",
                    at=at, detail={"parsed": parsed}))
            per.append(entry)
        n = len(artifacts or [])
        passed = not violations and n > 0
        return OracleResult(
            oracle_id=self.id, passed=passed,
            score=(sum(1 for e in per if e["ok"]) / n) if n else 0.0,
            violations=violations + ([] if n else [Violation(
                "no_export_artifacts", "nothing was exported", at=at)]),
            evidence={"per_artifact": per, "n": n},
            constraint_class=self.constraint_class, applicable=n > 0,
        )


@register
class RoundtripFidelity(Oracle):
    """§6.L ``roundtrip_fidelity``: read -> write -> read preserves semantics.

    N11 corrections baked in:
    * DICOM is compared **after semantic normalisation** (UIDs and timestamps
      necessarily change -- ``generate_uid()`` / ``datetime.now()``);
    * STL uses volume + watertightness + normals + Hausdorff, **not** vertex
      count;
    * dose grids use ``DoseGridScaling`` quantisation as the tolerance floor;
    * self-roundtrips of one importer/exporter pair are **not** sufficient --
      an independent implementation must agree (``independent_check``).
    """

    id = "roundtrip_fidelity"
    constraint_class = ConstraintClass.POSTCONDITION

    _SEMANTIC_KEYS = ("roi_names", "dose_scaling", "grid", "geometry", "labels", "numbers")

    def check(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
        *,
        fmt: str = "generic",
        independent: Optional[Dict[str, Any]] = None,
        dose_grid_scaling: Optional[float] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        gaps: List[Violation] = []

        # N11: an independent implementation must corroborate (§8.6 I3)
        if not independent:
            gaps.append(Violation(
                "roundtrip_self_only",
                "only the same importer/exporter pair was used; a shared bug "
                "would survive (N11). Supply an independent parser result.",
                at=at))

        if fmt == "stl":
            for k, tol in (("volume_mm3", 1e-4), ("watertight", 0.0),
                           ("hausdorff_mm", 1e-3)):
                a, b = first.get(k), second.get(k)
                if k == "watertight":
                    ok = a is True and b is True
                elif k in ("n_normals",):
                    ok = a == b
                else:
                    ok = (a is not None and b is not None and np.isfinite(float(a)) and np.isfinite(float(b))
                          and values_equal(a, b, "dose" if k == "volume_mm3" else "coord")[0])
                if not ok:
                    violations.append(Violation(
                        "stl_roundtrip_mismatch", f"{k}: {a} -> {b}", at=at))
            # Tessellation and normal/vertex counts may legitimately differ.
            return self._finish(violations, gaps, first, second, independent, at)

        if fmt in ("nifti", "dicom", "dose"):
            dose_tol = 1e-6
            if dose_grid_scaling is not None:
                if not np.isfinite(float(dose_grid_scaling)) or float(dose_grid_scaling) <= 0:
                    gaps.append(Violation("dose_scaling_invalid", "positive finite quantisation step required", at=at))
                else:
                    dose_tol = 0.5 * float(dose_grid_scaling)
            for k in ("dims", "origin", "spacing", "direction", "dtype"):
                a, b = first.get(k), second.get(k)
                if k in ("dims", "dtype"):
                    ok = a is not None and b is not None and a == b
                else:
                    aa, bb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
                    expected_size = 9 if k == "direction" else 3
                    ok = (aa.size == bb.size == expected_size and aa.shape == bb.shape
                          and np.isfinite(aa).all() and np.isfinite(bb).all()
                          and all(values_equal(x, y, "coord")[0] for x, y in zip(aa.reshape(-1), bb.reshape(-1))))
                if not ok:
                    violations.append(Violation(
                        "geometry_roundtrip_mismatch", f"{k}: {a} -> {b}", at=at))
            # N11: dose arrays compared at the DoseGridScaling quantisation floor
            if first.get("dose") is not None and second.get("dose") is not None:
                a = np.asarray(first["dose"], dtype=np.float64)
                b = np.asarray(second["dose"], dtype=np.float64)
                if a.shape != b.shape:
                    violations.append(Violation(
                        "dose_shape_roundtrip_mismatch", f"{a.shape} -> {b.shape}", at=at))
                else:
                    # N11: tolerance is half a quantisation step when known
                    tol = 0.5 * abs(float(dose_grid_scaling)) if dose_grid_scaling else 1e-6
                    err = float(np.max(np.abs(a - b))) if a.size else float("inf")
                    if not np.isfinite(a).all() or not np.isfinite(b).all() or err > tol:
                        violations.append(Violation(
                            "dose_roundtrip_quantisation_exceeded",
                            f"max|Δ| = {err:.6g} > 0.5*DoseGridScaling = {tol:.6g}",
                            at=at, detail={"err": err, "tol": tol}))
            if fmt == "dose" and (first.get("dose") is None or second.get("dose") is None):
                gaps.append(Violation("dose_array_missing", "dose fidelity requires actual decoded arrays", at=at))
            return self._finish(violations, gaps, first, second, independent, at, dose_tol=dose_tol)

        # generic: compare the declared semantic keys
        for k in self._SEMANTIC_KEYS:
            if k in first or k in second:
                if first.get(k) != second.get(k):
                    violations.append(Violation(
                        "semantic_roundtrip_mismatch", f"{k} changed", at=at))
        return self._finish(violations, gaps, first, second, independent, at)

    def _finish(self, violations, gaps, first, second, independent, at, dose_tol=1e-6):
        if not first or not second:
            gaps.append(Violation("roundtrip_empty", "nonempty semantic observations required", at=at))
        if independent is not None:
            keys = self._SEMANTIC_KEYS + ("dims", "origin", "spacing", "direction", "dose", "volume_mm3", "watertight")
            for k in keys:
                if k not in first and k not in second:
                    continue
                if k not in independent:
                    gaps.append(Violation("independent_field_missing", f"independent parser did not verify {k}", at=at))
                    continue
                a, b = first.get(k), independent[k]
                if k in ("dose", "origin", "spacing", "direction", "grid", "numbers") and not isinstance(a, dict):
                    aa, bb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
                    ok = (aa.size > 0 and aa.shape == bb.shape and np.isfinite(aa).all() and np.isfinite(bb).all()
                          and np.allclose(aa, bb, atol=dose_tol if k == "dose" else 1e-6, rtol=0))
                else:
                    ok = a == b
                if not ok:
                    violations.append(Violation("independent_parser_disagrees", f"{k}: independent implementation disagrees", at=at))
        applicable = not gaps
        passed = applicable and not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations, evidence_gaps=gaps,
            evidence={"independent_used": independent is not None},
            constraint_class=self.constraint_class,
            applicable=applicable,
            notes="R-b normalised semantic equivalence (N11); byte hashes are never compared",
        )


@register
class SemanticEquivalence(Oracle):
    """§6.H ``semantic_equivalence`` -- R-d / PRR_reply: two runs may differ in
    wording but must agree on conclusion, numbers and recommendation."""

    id = "semantic_equivalence"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        run_a: Dict[str, Any],
        run_b: Dict[str, Any],
        *,
        number_tol: float = 1e-9,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        dims = {}
        if not run_a or not run_b:
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("semantic_output_missing", "empty responses cannot establish consistency")])
        for key in ("conclusion", "recommendation", "refusal"):
            same = (run_a.get(key) == run_b.get(key))
            dims[key] = same
            if not same:
                violations.append(Violation(
                    "semantic_dimension_differ", f"{key} differs across reruns", at=at,
                    detail={"a": run_a.get(key), "b": run_b.get(key)}))
        na = run_a.get("numbers") or {}
        nb = run_b.get("numbers") or {}
        if set(na) != set(nb):
            violations.append(Violation(
                "semantic_number_set_differ",
                f"{sorted(na)} vs {sorted(nb)}", at=at))
        for k in sorted(set(na) & set(nb)):
            if not np.isfinite([float(na[k]), float(nb[k])]).all() or abs(float(na[k]) - float(nb[k])) > number_tol:
                violations.append(Violation(
                    "semantic_number_differ", f"{k}: {na[k]} vs {nb[k]}", at=at))
            dims.setdefault("numbers", True)
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations, evidence={"dimensions": dims, "number_tol": number_tol},
            constraint_class=self.constraint_class,
        )


@register
class ReplayHashArtifact(Oracle):
    """§6.H ``replay_hash_artifact`` -- R-a: same input, same *artefact* bytes.

    Only meaningful when deterministic kernels are in force (DESIGN §11.5:
    ``cudnn.benchmark=False`` / ``allow_tf32=False``; ``plans/dose_pre/inference.py``
    currently enables both).  Never applied to LLM reply text.
    """

    id = "replay_hash_artifact"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        runs: Sequence[Sequence[Dict[str, Any]]],
        *,
        deterministic_kernels: bool = False,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``runs`` is a list of runs; each run is a list of
        ``{"name": ..., "bytes": ...}`` artefacts."""
        gaps: List[Violation] = []
        if not deterministic_kernels:
            gaps.append(Violation(
                "deterministic_kernels_disabled",
                "PRR_artifact=1.0 is only required under deterministic kernels "
                "(`cudnn.benchmark=False`, `allow_tf32=False`); R2/R11",
                at=at))
        if len(runs) < 2:
            gaps.append(Violation(
                "fewer_than_two_runs", "replay needs >=2 runs to compare", at=at))
        violations: List[Violation] = []
        by_name: Dict[str, List[str]] = {}
        for run in runs or []:
            for a in run or []:
                by_name.setdefault(str(a.get("name")), []).append(
                    a.get("sha256") or _sha256_bytes(a.get("bytes") or b""))
        mismatched = {}
        for name, hashes in by_name.items():
            if len(set(hashes)) > 1:
                mismatched[name] = hashes
                violations.append(Violation(
                    "artifact_not_reproducible",
                    f"{name}: {len(set(hashes))} distinct hashes across runs", at=at))
        applicable = deterministic_kernels and len(runs) >= 2
        passed = applicable and not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations, evidence_gaps=gaps,
            evidence={"n_runs": len(runs or []), "artefacts": sorted(by_name),
                      "mismatched": mismatched, "deterministic_kernels": deterministic_kernels},
            constraint_class=self.constraint_class, applicable=applicable,
            notes="R-a only; LLM replies use SemanticEquivalence instead (R2)",
        )
