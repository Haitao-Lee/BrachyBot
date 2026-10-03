"""Judge infrastructure: the independent observers of DESIGN §8.6 I1-I3.

A checker is only as trustworthy as the data it reads.  The three helpers here
exist so that verdicts rest on **independent observation** rather than on what
the system under test says about itself (N8/BA-1):

* :class:`StateObserver` (I1) -- reads CWS from an out-of-band source and
  returns ``{"observed": ..., "claimed": ..., "mismatch": ...}``; ``observed``
  always wins.
* :class:`SideEffectAudit` (I2) -- records every side effect from *outside* the
  SUT; this is the trail the N1 invariant gate evaluates.
* :class:`IndependentParser` (I3) -- parses artefacts with an implementation
  that is not the producer's, so a shared import/export bug cannot hide.

They are deliberately dependency-free: the harness plugs in whatever backend
is available (db, files, pydicom, SimpleITK) through small adapters.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence

from oracles.evidence_keys import SELF_REPORTED_FLAGS, strip_self_reported


class StateObserver:
    """I1: replace self-reported conclusion flags with observed state."""

    def __init__(self, reader: Callable[[str], Dict[str, Any]]):
        """``reader(case_id) -> the authoritative CWS`` (from db/files, not
        from the SUT's response)."""
        self._reader = reader

    def observe(self, case_id: str, sut_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        observed = self._reader(case_id) or {}
        split = strip_self_reported(observed)
        result = {
            "observed": split["observed"],
            "claimed": split["claimed"],
            "mismatch": {},
            "self_report_mismatch": [],
        }
        if sut_state is not None:
            sut_split = strip_self_reported(sut_state)
            for key, claimed_val in split["claimed"].items():
                if claimed_val is None:
                    continue
                # a claimed flag with no observed support is a self-report
                # error -- surface it so CSMR can count it (BA-1 follow-through)
                path = key.split(".")
                node = sut_state
                for p in path:
                    node = (node or {}).get(p) if isinstance(node, dict) else None
                if node is not None and node != claimed_val:
                    result["self_report_mismatch"].append(
                        {"flag": key, "claimed": claimed_val, "sut_says": node})
            # a conclusion flag that the OBSERVED state does not support is a
            # self-report error (N8) -- this is where "claimed completed" while
            # the state is still draft gets caught.
            for k in ("completed", "verified", "roundtrip_ok"):
                claimed_anywhere = split["claimed"].get(f"plan.{k}", split["claimed"].get(k))
                sut_says = sut_split["claimed"].get(f"plan.{k}", sut_split["claimed"].get(k))
                if (claimed_anywhere or sut_says) and not _supports(split["observed"], k):
                    result["mismatch"][k] = True
                    result["self_report_mismatch"].append(
                        {"flag": k, "claimed": bool(claimed_anywhere or sut_says),
                         "observed_supports": False})
        return result


def _supports(observed: Dict[str, Any], flag: str) -> bool:
    """Is a conclusion flag backed by structure in the observed state?"""
    plan = observed.get("plan") or {}
    dose = observed.get("dose") or {}
    guide = observed.get("guide") or {}
    if flag == "completed":
        return plan.get("status") == "final"
    if flag == "verified":
        return bool(dose.get("computed"))
    if flag == "roundtrip_ok":
        return bool((observed.get("interop") or {}).get("last_export"))
    return True


class SideEffectAudit:
    """I2: an append-only trail of side effects, produced out of band."""

    def __init__(self, sink: Optional[List[Dict[str, Any]]] = None):
        self.entries: List[Dict[str, Any]] = sink if sink is not None else []
        self._seq = 0

    def record(self, kind: str, *, at: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        self._seq += 1
        entry = {"kind": kind, "at": at or f"step-{self._seq:06d}", "seq": self._seq, **fields}
        self.entries.append(entry)
        return entry

    def tool_call(self, tool: str, args: Any = None, ret: Any = None, **kw: Any):
        return self.record("tool_call", tool=tool, args=args, ret=ret, **kw)

    def file_op(self, op: str, target: str, **kw: Any):
        return self.record("file_op", op=op, target=target, **kw)

    def network_op(self, url: str, **kw: Any):
        return self.record("network_op", url=url, **kw)

    def export(self, fmt: str, path: str, **kw: Any):
        return self.record("export", format=fmt, target=path, **kw)

    def cross_case_ref(self, case_id: str, **kw: Any):
        return self.record("cross_case_ref", case_id=case_id, **kw)

    def completeness(self, expected_ops: Sequence[str]) -> Dict[str, Any]:
        """DESIGN §8.6 I2: every side effect must appear exactly once.

        ``expected_ops`` is the harness's own count of what the SUT did (from
        the syscall/db layer), so a missing entry is a *trailer* gap, not a
        judgement call.
        """
        seen = [e.get("op_id") or e.get("target") or e.get("tool") or e.get("url")
                for e in self.entries]
        expected, recorded = Counter(expected_ops), Counter(seen)
        missing = list((expected - recorded).elements())
        extra = list((recorded - expected).elements())
        return {
            "n_expected": len(expected_ops),
            "n_recorded": len(self.entries),
            "missing": missing,
            "extra_or_duplicate": extra,
            "exactly_once": not missing and not extra,
            "completeness": (1.0 - len(missing) / len(expected_ops)) if expected_ops else 1.0,
        }


class IndependentParser:
    """I3: parse artefacts with an implementation the producer does not own."""

    def __init__(self, nifti=None, dicom=None, pdf=None, stl=None):
        """Each backend is a callable returning a plain dict; pass only what is
        available.  Missing backends degrade to an evidence gap, never a pass.
        """
        self._nifti = nifti
        self._dicom = dicom
        self._pdf = pdf
        self._stl = stl

    def parse(self, fmt: str, path: str) -> Dict[str, Any]:
        fmt = (fmt or "").lower()
        try:
            backend = {"nifti": self._nifti, "dicom": self._dicom, "rt_dose": self._dicom,
                       "rt_struct": self._dicom, "rt_plan": self._dicom,
                       "pdf": self._pdf, "stl": self._stl}.get(fmt)
            if backend is None:
                return {"ok": False, "reason": f"no independent backend for {fmt!r}", "independent": False}
            parsed = backend(path)
            if not isinstance(parsed, dict) or not parsed:
                return {"ok": False, "reason": "independent parser returned no semantic data", "independent": True}
            return {"ok": True, "parsed": parsed, "independent": True}
        except Exception as exc:  # noqa: BLE001 -- a parse failure is a finding
            return {"ok": False, "reason": repr(exc), "independent": True}

    @staticmethod
    def semantic_normalise(dicom: Dict[str, Any]) -> Dict[str, Any]:
        """N11 / R-b: drop the fields that *must* change on re-export.

        ``dicom_rt_exporter`` mints ``generate_uid()`` and ``datetime.now()``
        per export, so byte comparison is meaningless; only normalised
        semantics are.
        """
        volatile = {
            "ImplementationClassUID",
            "StudyDate", "StudyTime", "StructureSetDate", "StructureSetTime",
            "InstanceCreationDate", "InstanceCreationTime",
        }
        aliases = {}
        def normalise(value, key=""):
            if isinstance(value, dict):
                return {k: normalise(value[k], str(k)) for k in sorted(value)
                        if k not in volatile}
            if isinstance(value, (list, tuple)):
                return [normalise(v, key) for v in value]
            # Class/transfer-syntax UIDs identify standards, not generated instances.
            if key.endswith("UID") and key not in ("SOPClassUID", "ReferencedSOPClassUID", "TransferSyntaxUID"):
                return aliases.setdefault(str(value), f"instance-{len(aliases)}")
            return value
        # Retain the reference graph: reminting identifiers is allowed; changing
        # which instance a sequence points to is not semantic equivalence.
        return normalise(dicom)


def default_nifti_backend():
    """SimpleITK-backed reader, used when available (I3 in production)."""
    def read(path: str) -> Dict[str, Any]:
        import SimpleITK as sitk
        img = sitk.ReadImage(path)
        return {
            "dims": list(img.GetSize()),
            "origin": list(img.GetOrigin()),
            "spacing": list(img.GetSpacing()),
            "direction": list(img.GetDirection()),
            "dtype": img.GetPixelIDTypeAsString(),
        }
    return read


def default_dicom_backend():
    """pydicom-backed reader with volatile tags stripped."""
    def read(path: str) -> Dict[str, Any]:
        import pydicom
        ds = pydicom.dcmread(path)
        def plain(dataset):
            out = {}
            for element in dataset:
                key = element.keyword or str(element.tag)
                if element.VR == "SQ":
                    out[key] = [plain(item) for item in element.value]
                elif isinstance(element.value, bytes):
                    out[key] = {"bytes_sha256": hashlib.sha256(element.value).hexdigest(),
                                "nbytes": len(element.value)}
                elif isinstance(element.value, (str, int, float)):
                    out[key] = element.value
                else:
                    try:
                        out[key] = list(element.value)
                    except TypeError:
                        out[key] = str(element.value)
            return out
        raw = plain(ds)
        return IndependentParser.semantic_normalise(raw)
    return read


def default_pdf_backend():
    def read(path: str) -> Dict[str, Any]:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        document = PdfReader(path, strict=True)
        return {
            "nbytes": os.path.getsize(path), "pages": len(document.pages),
            "text": "\n".join(page.extract_text() or "" for page in document.pages),
        }
    return read
