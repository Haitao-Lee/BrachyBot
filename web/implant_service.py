"""Durable, explicitly scoped SeedFinder reconstruction and human review service.

Construct scopes, inputs and review authorizations at the authenticated server
boundary. They are opaque injected objects, not client-provided credentials.
This service owns a bounded artifact journal inside the captured case workspace;
it never changes the agent's active CT, preoperative plan, dose or guide. The
pipeline must consume the returned dependency invalidation receipt and register
these artifact references in its export/retention graph.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Optional
from uuid import UUID, uuid4

import SimpleITK as sitk

from tool_factory.seed_seg.seedfinder_adapter import (
    CODE_FILES, SeedFinderAdapter, SeedFinderModelContract, SeedFinderRequest,
    SubprocessSeedFinderRunner, sha256_file,
)
from utils.cancellation import OperationCancelled, is_cancelled
from utils.implant_reconstruction import (
    ImageReference, ObservationReview, OrientationProfile, ReconstructionCancelled,
    SeedAxisReconstruction, SeedDimensions, SeedObservation, AxisDiagnostics,
    check_execution, review_observations, seed_presentation,
)

IMPLANT_MEMORY_KEY = "implanted_seed_reconstruction"
MAX_JSON_BYTES = 16_000_000
DEPENDENT_FAMILIES = ("baseline_dose", "supplemental_plan", "metrics", "report")


class ImplantServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(x) < 32 for x in value):
        raise ImplantServiceError("invalid_implant_scope", "A stable captured identity is required")
    return value


def _uuid(value):
    try:
        return UUID(value).hex
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImplantServiceError("invalid_implant_revision", "Use the returned revision/request UUID") from exc


def _same_revision(first, second):
    return first is None and second is None or first is not None and second is not None and _uuid(first) == _uuid(second)


def _inside(path: Path, root: Path):
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ImplantServiceError("implant_path_outside_scope", "Implant artifacts must remain inside the owned case root")
    return resolved


@dataclass(frozen=True)
class ImplantScope:
    owner_id: str
    session_id: str
    timepoint_id: str
    workspace_root: str
    image_id: Optional[str] = None

    def __post_init__(self):
        for value in (self.owner_id, self.session_id, self.timepoint_id):
            _identifier(value)
        path = Path(self.workspace_root)
        if not path.is_absolute() or not path.is_dir():
            raise ImplantServiceError("invalid_implant_scope", "Bind an existing absolute owned case workspace")
        object.__setattr__(self, "workspace_root", str(path.resolve()))
        if self.image_id is not None:
            _identifier(self.image_id)

    @property
    def identities(self):
        return {"owner_id": self.owner_id, "session_id": self.session_id, "timepoint_id": self.timepoint_id,
                **({"image_id": self.image_id} if self.image_id is not None else {})}

    @property
    def artifact_root(self):
        namespace = hashlib.sha256(_encoded(self.identities)).hexdigest()[:32]
        return _inside(Path(self.workspace_root) / "artifacts" / "implant_reconstruction" / namespace,
                       Path(self.workspace_root))


@dataclass(frozen=True)
class ImplantInput:
    image_ref: ImageReference
    ct_path: str
    owned_input_root: str
    preoperative_timepoint_id: Optional[str]
    stage: str = "intraoperative"
    modality: str = "CT"

    def __post_init__(self):
        if not isinstance(self.image_ref, ImageReference):
            raise ImplantServiceError("invalid_implant_input", "Inject the captured typed image revision")
        if self.stage not in {"preoperative", "intraoperative"} or self.modality != "CT":
            raise ImplantServiceError("unsupported_implant_image", "The supplied SeedFinder workflow requires a CT observation")
        if self.stage == "intraoperative" or self.preoperative_timepoint_id is not None:
            _identifier(self.preoperative_timepoint_id)
        if self.preoperative_timepoint_id == self.image_ref.timepoint_id:
            raise ImplantServiceError("invalid_implant_source", "Bind a separate owned preoperative timepoint")


@dataclass(frozen=True)
class SeedFinderRuntimeConfig:
    """Trusted worker configuration. No bundle discovery, installation or model fallback."""
    bundle_dir: str
    python_executable: str
    device: str = "cpu"
    timeout_seconds: float = 900.0
    sw_batch_size: int = 1
    max_jobs: int = 1024
    max_revisions: int = 1024
    max_storage_bytes: int = 2_000_000_000

    def __post_init__(self):
        if self.device != "cpu" and not (self.device.startswith("cuda:") and self.device[5:].isdigit()):
            raise ImplantServiceError("invalid_seedfinder_device", "Configure an explicit cpu or cuda:N SeedFinder device")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 3600:
            raise ValueError("SeedFinder timeout must be finite and within (0, 3600] seconds")
        for name in ("sw_batch_size", "max_jobs", "max_revisions", "max_storage_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("BRACHYBOT_SEEDFINDER_BUNDLE", ""),
                   os.environ.get("BRACHYBOT_SEEDFINDER_PYTHON", ""),
                   device=os.environ.get("BRACHYBOT_SEEDFINDER_DEVICE", "cpu"))

    def validate_available(self):
        message = (
            "SeedFinder reconstruction is unavailable. Configure BRACHYBOT_SEEDFINDER_BUNDLE to the "
            "owned, pinned supplied bundle on Linux and BRACHYBOT_SEEDFINDER_PYTHON to an existing "
            "compatible inference interpreter. The bundle must contain all three supplied source files "
            "and models/best_autoencoder.pth. No inference or automatic installation was performed."
        )
        bundle, python = Path(self.bundle_dir), Path(self.python_executable)
        if (os.name != "posix" or not self.bundle_dir or not self.python_executable or
                not bundle.is_absolute() or not bundle.is_dir() or not python.is_absolute() or
                not python.is_file() or not os.access(python, os.X_OK) or
                any(not (bundle / name).is_file() for name in CODE_FILES) or
                not (bundle / "models" / "best_autoencoder.pth").is_file()):
            raise ImplantServiceError("seedfinder_not_configured", message)
        if self.device != "cpu" and os.environ.get("CUDA_VISIBLE_DEVICES"):
            raise ImplantServiceError(
                "seedfinder_device_namespace_ambiguous",
                "Configure the SeedFinder worker in an unmasked CUDA device namespace so its device lease "
                "and shared GPU lock identify the same physical card; CUDA_VISIBLE_DEVICES is currently set.")


@dataclass(frozen=True)
class ImplantReviewAuthorization:
    """Issued by a trusted human-review handler, never reconstructed from tool JSON."""
    owner_id: str
    image_ref: ImageReference
    expected_revision_id: str
    reviewer_id: str

    def __post_init__(self):
        _identifier(self.owner_id)
        _identifier(self.reviewer_id)
        _uuid(self.expected_revision_id)
        if not isinstance(self.image_ref, ImageReference):
            raise ValueError("Review authorization requires the captured image revision")


@dataclass(frozen=True)
class ImplantReviewRequest:
    authorization: ImplantReviewAuthorization
    decisions: tuple[ObservationReview, ...]
    coverage_status: Optional[str] = None
    set_review_evidence: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.authorization, ImplantReviewAuthorization):
            raise ImplantServiceError("implant_review_authorization_required", "Review requires an authenticated human-review authorization")
        object.__setattr__(self, "decisions", tuple(self.decisions))
        if len(self.decisions) > 1024 or any(not isinstance(x, ObservationReview) for x in self.decisions):
            raise ValueError("Review decisions must be bounded typed observation decisions")
        if self.coverage_status not in (None, "unknown", "partial", "complete"):
            raise ValueError("Invalid scan coverage state")
        if any(len(x.evidence) > 4000 for x in self.decisions) or (
                self.set_review_evidence is not None and (not isinstance(self.set_review_evidence, str) or
                                                          len(self.set_review_evidence) > 4000)):
            raise ValueError("Review evidence exceeds its text limit")
        if self.coverage_status == "complete" and not self.set_review_evidence:
            raise ImplantServiceError("implant_coverage_evidence_required", "Complete scan coverage requires explicit set-review evidence")


@dataclass(frozen=True)
class ImplantCorrectionRequest:
    """Authenticated observation edits, never physical surgery or dose approval."""
    authorization: ImplantReviewAuthorization
    request_id: str
    action: str
    observation_ids: tuple[str, ...] = ()
    center_lps_mm: Optional[tuple] = None

    def __post_init__(self):
        if not isinstance(self.authorization, ImplantReviewAuthorization):
            raise ValueError("A typed correction authorization is required")
        object.__setattr__(self,'request_id',_uuid(self.request_id))
        if self.action not in {"add", "move", "exclude", "restore"}:
            raise ValueError("Unknown observation correction")
        object.__setattr__(self, "observation_ids", tuple(self.observation_ids))
        if len(set(self.observation_ids)) != len(self.observation_ids) or len(self.observation_ids) > 1024:
            raise ValueError("Correction targets must be unique and bounded")
        for value in self.observation_ids:
            _uuid(value)
        if (self.action == "add" and self.observation_ids) or (
                self.action == "move" and len(self.observation_ids) != 1) or (
                self.action in {"exclude", "restore"} and not self.observation_ids):
            raise ValueError("Correction targets do not match the action")
        if self.action in {"add", "move"}:
            values = tuple(self.center_lps_mm or ())
            if len(values) != 3 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                raise ValueError("Use exactly three finite physical LPS coordinates in mm")
            object.__setattr__(self, "center_lps_mm", values)
        elif self.center_lps_mm is not None:
            raise ValueError("This correction does not accept a center")


def _default_lease(*, caller, prefer):
    from plans.device_manager import device_session
    return device_session(caller=caller, prefer=prefer)


@contextmanager
def _file_lock(path: Path, *, cancelled=None, deadline=None, wait=True):
    """Linux flock; GPU filenames agree with the existing CTV cross-process guard."""
    if os.name != "posix":
        raise ImplantServiceError("implant_lock_unavailable", "The reconstruction worker requires Linux file locking")
    import fcntl
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ImplantServiceError("unsafe_implant_lock", "Lock files must not be symlinks")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(descriptor).st_nlink != 1 or os.fstat(descriptor).st_uid != os.getuid():
            raise ImplantServiceError("unsafe_implant_lock", "Lock file ownership is invalid")
        while True:
            check_execution(cancelled, deadline)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait:
                    raise ImplantServiceError("implant_job_in_progress", "This reconstruction request is already running")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextmanager
def _default_device_lock(device, *, cancelled, deadline):
    directory = Path(tempfile.gettempdir()) / f"brachybot-ctv-gpu-{os.getuid()}"
    filename = "cpu.lock" if device == "cpu" else f"gpu-{int(device.split(':')[1])}.lock"
    with _file_lock(directory / filename, cancelled=cancelled, deadline=deadline):
        yield


class LeasedSeedFinderRunner:
    """Bind the leased GPU in the child, without changing process-global environment.

    The adapter's CLI accepts 'cuda', so a cuda:1 lease must explicitly expose
    card 1 as child cuda:0. The exact pinned entry point still handles all model
    preprocessing, inference and output. Cancellation stays in its existing runner.
    """
    _CUDA_ENTRY = (
        "import os,runpy,sys;gpu,script=sys.argv[1:3];"
        "os.environ['CUDA_VISIBLE_DEVICES']=gpu;sys.argv=sys.argv[2:];"
        "sys.path.insert(0,os.path.dirname(script));runpy.run_path(script,run_name='__main__')"
    )

    def __init__(self, runner, device):
        self.runner, self.device = runner, device

    def execute(self, prepared, *, cancelled=None):
        if self.device != "cpu":
            command = prepared.command
            if len(command) < 3 or command[1] != "-B":
                raise ValueError("Unexpected pinned SeedFinder invocation contract")
            prepared = replace(prepared, command=(command[0], "-B", "-c", self._CUDA_ENTRY,
                                                  self.device.split(":")[1], *command[2:]))
        return self.runner.execute(prepared, cancelled=cancelled)


class ImplantService:
    """Atomic immutable revisions, a CAS head, bounded job receipts and memory hydration.

    Disk publication is authoritative. A crash before head publication leaves
    staged/orphan artifacts; after publication, get() restores the memory cache.
    Failed jobs are not silently retried. A new explicit request UUID is required.
    """

    def __init__(self, scope: ImplantScope, memory, *, runtime: Optional[SeedFinderRuntimeConfig] = None,
                 adapter_factory: Callable = SeedFinderAdapter, runner_factory: Callable = SubprocessSeedFinderRunner,
                 lease_factory: Callable = _default_lease, device_lock_factory: Callable = _default_device_lock,
                 capacity_check: Optional[Callable[[Path, int], None]] = None,
                 image_fence: Optional[Callable[[ImageReference], bool]] = None):
        if not isinstance(scope, ImplantScope) or getattr(memory, "session_id", None) != scope.session_id:
            raise ImplantServiceError("invalid_implant_scope", "Bind memory from the captured authenticated Session")
        if not all(hasattr(memory, name) for name in ("_lock", "retrieve", "store")):
            raise ValueError("Implant service requires lockable persistent agent memory")
        self.scope, self.memory, self.runtime = scope, memory, runtime
        self.adapter_factory, self.runner_factory = adapter_factory, runner_factory
        self.lease_factory, self.device_lock_factory = lease_factory, device_lock_factory
        self.capacity_check = capacity_check
        self.image_fence = image_fence

    @property
    def root(self):
        return self.scope.artifact_root

    def _config(self):
        return self.runtime or SeedFinderRuntimeConfig.from_environment()

    def _limits(self):
        # Reading/reviewing saved observations never requires inference assets
        # or a currently valid worker device environment.
        return self.runtime or SeedFinderRuntimeConfig("", "")

    def _empty_index(self):
        return {"schema_version": 1, "scope": self.scope.identities, "generation": 0,
                "current": None, "history": [], "jobs": {}}

    def _read_json(self, path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            raise ImplantServiceError("implant_journal_integrity_error", "Implant metadata is missing, unsafe or oversized")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ImplantServiceError("implant_journal_integrity_error", "Implant metadata is unreadable") from exc
        return value

    def _read_index(self):
        path = self.root / "index.json"
        if not path.exists():
            return self._empty_index()
        value = self._read_json(path)
        if (not isinstance(value, dict) or value.get("schema_version") != 1 or
                value.get("scope") != self.scope.identities or not isinstance(value.get("history"), list) or
                not isinstance(value.get("jobs"), dict) or len(value["history"]) > self._limits().max_revisions or
                len(value["jobs"]) > self._limits().max_jobs or isinstance(value.get("generation"), bool) or
                not isinstance(value.get("generation"), int) or value["generation"] < 0):
            raise ImplantServiceError("implant_journal_integrity_error", "Implant journal scope/schema/limits disagree")
        if value.get("current") is not None and value["current"] not in value["history"]:
            raise ImplantServiceError("implant_journal_integrity_error", "The current implant revision is not in its history")
        return value

    def _capacity(self, path, size):
        files = list(self.root.rglob("*")) if self.root.exists() else []
        if len(files) > 2048 or any(x.is_symlink() for x in files):
            raise ImplantServiceError("implant_storage_limit", "Implant artifact count or containment limit reached")
        used = sum(x.stat().st_size for x in files if x.is_file())
        replacement = path.stat().st_size if path.is_file() else 0
        if used - replacement + size > self._limits().max_storage_bytes:
            raise ImplantServiceError("implant_storage_limit", "Owned implant storage limit reached; retain/reclaim artifacts through the workspace manager")
        if self.capacity_check is not None:
            self.capacity_check(path, size)

    def _atomic_json(self, path, value):
        payload = _encoded(value)
        if len(payload) > MAX_JSON_BYTES:
            raise ImplantServiceError("implant_metadata_limit", "Implant revision exceeds its metadata limit")
        self._capacity(path, len(payload))
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def _journal(self, *, cancelled=None, deadline=None):
        root = self.root
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        _inside(root, Path(self.scope.workspace_root))
        with _file_lock(root / "journal.lock", cancelled=cancelled, deadline=deadline):
            yield self._read_index()

    def _check_input(self, input_value, *, cancelled, deadline):
        if not isinstance(input_value, ImplantInput):
            raise ImplantServiceError("invalid_implant_input", "Inject an owned ImplantInput for the selected intraoperative CT")
        reference = input_value.image_ref
        if reference.session_id != self.scope.session_id or reference.timepoint_id != self.scope.timepoint_id:
            raise ImplantServiceError("invalid_implant_scope", "The captured CT belongs to a different Session/timepoint")
        if self.image_fence is not None and not self.image_fence(reference):
            raise ImplantServiceError("implant_input_changed", "The captured timepoint image revision is no longer current")
        root = Path(self.scope.workspace_root)
        inputs = Path(input_value.owned_input_root)
        ct = Path(input_value.ct_path)
        if not inputs.is_absolute() or not ct.is_absolute() or not inputs.is_dir():
            raise ImplantServiceError("invalid_implant_input", "Capture absolute owned CT/input paths")
        inputs = _inside(inputs, root)
        ct = _inside(ct, inputs)
        if not ct.is_file() or ct.stat().st_nlink != 1 or not ct.name.lower().endswith((".nii", ".nii.gz")):
            raise ImplantServiceError("invalid_implant_input", "SeedFinder requires a regular owned NIfTI CT")
        if sha256_file(ct, cancelled=cancelled, deadline=deadline, max_bytes=512_000_000) != reference.image_sha256:
            raise ImplantServiceError("implant_input_changed", "The selected CT changed; capture its new image revision before reconstructing")
        return ct, inputs

    def _cas(self, index, expected):
        actual = index["current"]["revision_id"] if index["current"] else None
        if not _same_revision(actual, expected):
            raise ImplantServiceError("implant_revision_conflict", "Implant observations changed; read get_reconstruction and use its current revision UUID")

    def _artifact(self, path, role, *, cancelled=None, deadline=None):
        path = _inside(Path(path), self.root)
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ImplantServiceError("implant_artifact_integrity_error", "Implant artifacts must be regular owned files")
        return {"role": role, "path": str(path.relative_to(Path(self.scope.workspace_root))),
                "sha256": sha256_file(path, cancelled=cancelled, deadline=deadline, max_bytes=512_000_000)}

    def _load_record(self, reference, *, cancelled=None, deadline=None):
        path = _inside(Path(self.scope.workspace_root) / reference["path"], self.root)
        if sha256_file(path, cancelled=cancelled, deadline=deadline, max_bytes=MAX_JSON_BYTES) != reference["sha256"]:
            raise ImplantServiceError("implant_journal_integrity_error", "Immutable implant revision hash disagrees")
        record = self._read_json(path)
        if record.get("scope") != self.scope.identities or record.get("clinical_use_ready") is not False:
            raise ImplantServiceError("implant_journal_integrity_error", "Immutable implant revision scope or acceptance disagrees")
        reconstruction = SeedAxisReconstruction.from_dict(record["reconstruction"])
        if (not _same_revision(reconstruction.revision_id, reference["revision_id"]) or
                reconstruction.image_ref.session_id != self.scope.session_id or
                reconstruction.image_ref.timepoint_id != self.scope.timepoint_id):
            raise ImplantServiceError("implant_journal_integrity_error", "Immutable implant image/revision identity disagrees")
        for artifact in record["artifacts"]:
            path = _inside(Path(self.scope.workspace_root) / artifact["path"], self.root)
            actual = self._artifact(path, artifact["role"], cancelled=cancelled, deadline=deadline)
            if actual != artifact:
                raise ImplantServiceError("implant_artifact_integrity_error", "A referenced implant artifact changed")
        return record

    def _hydrate_memory(self, index, record):
        # One atomic catalog update; no swapping of global CT/active memory.
        with self.memory._lock:
            catalog = copy.deepcopy(self.memory.retrieve(IMPLANT_MEMORY_KEY) or {"schema_version": 1, "by_timepoint": {}})
            if catalog.get("schema_version") != 1 or not isinstance(catalog.get("by_timepoint"), dict):
                raise ImplantServiceError("implant_memory_integrity_error", "The implant memory catalog has an unsupported schema")
            prior = catalog["by_timepoint"].get(self.scope.timepoint_id)
            if prior is not None and prior.get("scope") != self.scope.identities:
                raise ImplantServiceError("implant_memory_integrity_error", "The timepoint memory cache belongs to another captured owner/Session")
            entry = {
                "scope": self.scope.identities, "generation": index["generation"],
                "current": copy.deepcopy(record), "history": copy.deepcopy(index["history"]),
                "dependency_invalidation": {"state": "required", "applied": False,
                                             "observation_revision_id": record["reconstruction"]["revision_id"],
                                             "families": list(DEPENDENT_FAMILIES)},
            }
            if prior == entry:
                return
            catalog["by_timepoint"][self.scope.timepoint_id] = entry
            self.memory.store(IMPLANT_MEMORY_KEY, catalog)

    def _envelope(self, reconstruction, artifacts, source, request_id):
        states = [x.review_status for x in reconstruction.observations]
        record = {"schema_version": 1, "scope": self.scope.identities,
                "reconstruction": reconstruction.to_dict(), "artifacts": artifacts,
                "preoperative_timepoint_id": source, "request_id": request_id, "created_at": _utc_now(),
                "counts": {"detected_count": len(states), "accepted_count": states.count("accepted"),
                           "review_needed_count": states.count("review_needed"), "excluded_count": states.count("rejected")},
                "clinical_use_ready": False, "research_only": True,
                "dependency_invalidation": {"state": "required", "applied": False, "families": list(DEPENDENT_FAMILIES)}}
        # Publish the same JSON-compatible value before and after cold restore.
        # Typed tuples are restored only through SeedAxisReconstruction.from_dict.
        return json.loads(_encoded(record))

    def _publish(self, index, record, expected, *, request_id=None):
        self._cas(index, expected)
        if len(index["history"]) >= self._limits().max_revisions:
            raise ImplantServiceError("implant_revision_limit", "Implant revision history limit reached; preserve it through workspace archival")
        reconstruction = record["reconstruction"]
        path = self.root / "revisions" / (_uuid(reconstruction["revision_id"]) + ".json")
        if path.exists():
            raise ImplantServiceError("implant_revision_conflict", "Immutable revision UUID already exists")
        self._atomic_json(path, record)
        reference = {"revision_id": reconstruction["revision_id"], "path": str(path.relative_to(Path(self.scope.workspace_root))),
                     "sha256": hashlib.sha256(_encoded(record)).hexdigest()}
        index["history"].append(reference)
        index["current"] = reference
        index["generation"] += 1
        if request_id:
            index["jobs"][request_id].update(status="completed", revision=reference, completed_at=_utc_now())
        self._atomic_json(self.root / "index.json", index)
        return reference

    def reconstruct(self, input_value: ImplantInput, *, request_id: str,
                    expected_revision_id: Optional[str] = None, dimensions: Optional[SeedDimensions] = None,
                    profile: OrientationProfile = OrientationProfile(), cancelled=None,
                    deadline: Optional[float] = None):
        config = self._config()
        config.validate_available()
        deadline = min(deadline, time.monotonic() + config.timeout_seconds) if deadline is not None else time.monotonic() + config.timeout_seconds
        check_execution(cancelled, deadline)
        ct, inputs = self._check_input(input_value, cancelled=cancelled, deadline=deadline)
        request_id = _uuid(request_id)
        contract = SeedFinderModelContract.for_supplied_bundle(config.bundle_dir)
        signature = hashlib.sha256(_encoded({"input": asdict(input_value), "contract": asdict(contract),
                                             "profile": asdict(profile), "dimensions": asdict(dimensions) if dimensions else None,
                                             "device": config.device, "sw_batch_size": config.sw_batch_size})).hexdigest()
        with self._journal(cancelled=cancelled, deadline=deadline) as index:
            if request_id not in index["jobs"] and len(index["jobs"]) >= config.max_jobs:
                raise ImplantServiceError("implant_job_limit", "The bounded implant job journal is full; archive/reclaim it through the workspace manager")
            jobs = self.root / "jobs"
            if request_id not in index["jobs"] and jobs.exists() and len(list(jobs.glob("*.lock"))) >= config.max_jobs:
                raise ImplantServiceError("implant_job_limit", "The bounded implant staging directory is full; archive/reclaim it through the workspace manager")
        with _file_lock(self.root / "jobs" / (request_id + ".lock"), cancelled=cancelled, deadline=deadline, wait=False):
            with self._journal(cancelled=cancelled, deadline=deadline) as index:
                prior_job = index["jobs"].get(request_id)
                if prior_job:
                    if prior_job["input_signature"] != signature:
                        raise ImplantServiceError("implant_request_conflict", "This request UUID was already bound to different image/configuration inputs")
                    if prior_job["status"] == "completed":
                        record = self._load_record(prior_job["revision"], cancelled=cancelled, deadline=deadline)
                        current = self._load_record(index["current"], cancelled=cancelled, deadline=deadline)
                        self._hydrate_memory(index, current)
                        return self._receipt(record, index)
                    if prior_job["status"] == "running":
                        prior_job.update(status="interrupted", error_code="worker_interrupted")
                        self._atomic_json(self.root / "index.json", index)
                    raise ImplantServiceError("implant_job_requires_new_request", "This staged job did not commit; inspect its receipt and submit a new explicit request UUID")
                self._cas(index, expected_revision_id)
                if len(index["jobs"]) >= config.max_jobs:
                    raise ImplantServiceError("implant_job_limit", "The bounded implant job journal is full; archive/reclaim it through the workspace manager")
                index["jobs"][request_id] = {"status": "running", "input_signature": signature,
                                             "expected_revision_id": expected_revision_id, "started_at": _utc_now()}
                self._atomic_json(self.root / "index.json", index)
            output = self.root / "jobs" / (request_id + "-output")
            request = SeedFinderRequest(input_value.image_ref, str(ct), str(inputs), str(self.root / "jobs"),
                                        str(output), config.python_executable, contract,
                                        device="cpu" if config.device == "cpu" else "cuda",
                                        sw_batch_size=config.sw_batch_size, deadline_monotonic=deadline,
                                        max_artifact_bytes=512_000_000)
            try:
                adapter = self.adapter_factory(LeasedSeedFinderRunner(self.runner_factory(), config.device))
                # Validate pinned assets/image before leasing a device. run()
                # revalidates at execution, so changes while queued fail closed.
                try:
                    adapter.prepare(request, cancelled=cancelled)
                except (ValueError, OSError) as exc:
                    raise ImplantServiceError(
                        "seedfinder_validation_failed", f"SeedFinder asset/image validation failed: {exc}. "
                        "Verify the configured Linux bundle/interpreter and pinned source/model files.") from exc
                preferred = "cpu" if config.device == "cpu" else config.device.split(":")[1]
                with self.lease_factory(caller="seedfinder:" + self.root.name, prefer=preferred) as lease:
                    check_execution(cancelled, deadline)
                    if lease.device_str != config.device:
                        raise ImplantServiceError("seedfinder_device_unavailable", "The configured SeedFinder device could not be leased; no automatic CPU/GPU fallback was used")
                    with self.device_lock_factory(config.device, cancelled=cancelled, deadline=deadline):
                        detected = adapter.run(request, cancelled=cancelled, execution_guard=nullcontext())
                        # The adapter selects the pinned supplied direction provider by default.
                        reconstruction = adapter.reconstruct(detected, profile=profile, dimensions=dimensions,
                                                            cancelled=cancelled, deadline=deadline)
                check_execution(cancelled, deadline)
                if reconstruction.image_ref != input_value.image_ref:
                    raise ImplantServiceError("implant_input_changed", "The provider returned a different captured image revision")
                if (reconstruction.provider_id != "supplied-seedfinder-xy-deposition" or
                        reconstruction.provider_version != dict(contract.code_sha256)["seed_pipeline_deepdec_roi.py"]):
                    raise ImplantServiceError("implant_provider_contract_changed", "The pinned supplied direction provider was not used")
                if not input_value.image_ref.geometry.agrees_with(detected.original_grid_mask):
                    raise ImplantServiceError("implant_mask_geometry_invalid", "The reconstruction mask does not match the original CT grid")
                if reconstruction.review_status != "review_needed" or any(
                        x.review_status != "review_needed" for x in reconstruction.observations):
                    raise ImplantServiceError("implant_provider_autoaccept_forbidden", "Detection/orientation cannot approve implanted observations")
                with self._journal(cancelled=cancelled, deadline=deadline) as index:
                    self._cas(index, expected_revision_id)
                    self._check_input(input_value, cancelled=cancelled, deadline=deadline)
                    artifacts = []
                    for artifact in detected.artifacts:
                        item = self._artifact(artifact.path, artifact.role, cancelled=cancelled, deadline=deadline)
                        if item["sha256"] != artifact.sha256:
                            raise ImplantServiceError("implant_artifact_integrity_error", "A detector artifact changed before publication")
                        artifacts.append(item)
                    mask_path = self.root / "revisions" / (_uuid(reconstruction.revision_id) + "-original-mask.nii.gz")
                    mask_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    if mask_path.exists():
                        raise ImplantServiceError("implant_revision_conflict", "Immutable original-grid mask already exists")
                    self._capacity(mask_path, math.prod(detected.original_grid_mask.GetSize()) + 8192)
                    sitk.WriteImage(detected.original_grid_mask, str(mask_path), True)
                    with mask_path.open("rb") as handle:
                        os.fsync(handle.fileno())
                    artifacts.append(self._artifact(mask_path, "original_grid_mask", cancelled=cancelled, deadline=deadline))
                    record = self._envelope(reconstruction, artifacts, input_value.preoperative_timepoint_id, request_id)
                    check_execution(cancelled, deadline)
                    self._publish(index, record, expected_revision_id, request_id=request_id)
                    self._hydrate_memory(index, record)
                    return self._receipt(record, index)
            except BaseException as exc:
                # A published disk head survives memory callback failures. Never
                # rewrite a completed receipt as failed after the commit boundary.
                with self._journal(deadline=time.monotonic() + 5) as index:
                    if index["jobs"][request_id]["status"] != "completed":
                        index["jobs"][request_id].update(status="failed", error_code=getattr(exc, "code", type(exc).__name__))
                        self._atomic_json(self.root / "index.json", index)
                raise

    def get(self, *, revision_id: Optional[str] = None, cancelled=None, deadline=None):
        check_execution(cancelled, deadline)
        if not (self.root / "index.json").is_file():
            raise ImplantServiceError("implant_reconstruction_not_found", "No reconstruction is saved for this captured timepoint")
        with self._journal(cancelled=cancelled, deadline=deadline) as index:
            current = index["current"]
            if current is None:
                raise ImplantServiceError("implant_reconstruction_not_found", "No implant job has committed a reconstruction")
            target = current if revision_id is None else next(
                (x for x in index["history"] if _same_revision(x["revision_id"], revision_id)), None)
            if target is None:
                raise ImplantServiceError("implant_reconstruction_not_found", "This revision is not in the owned timepoint history")
            record = self._load_record(target, cancelled=cancelled, deadline=deadline)
            current_record = record if target == current else self._load_record(current, cancelled=cancelled, deadline=deadline)
            self._hydrate_memory(index, current_record)
            return self._receipt(record, index)

    def review(self, request: ImplantReviewRequest, *, cancelled=None, deadline=None):
        if not isinstance(request, ImplantReviewRequest):
            raise ImplantServiceError("implant_review_authorization_required", "Inject a typed authenticated human-review request; tool JSON cannot grant approval")
        auth = request.authorization
        if (auth.owner_id != self.scope.owner_id or auth.image_ref.session_id != self.scope.session_id or
                auth.image_ref.timepoint_id != self.scope.timepoint_id):
            raise ImplantServiceError("invalid_implant_scope", "The review authorization belongs to another owner/Session/timepoint")
        check_execution(cancelled, deadline)
        with self._journal(cancelled=cancelled, deadline=deadline) as index:
            self._cas(index, auth.expected_revision_id)
            if not index["current"]:
                raise ImplantServiceError("implant_reconstruction_not_found", "Reconstruct the selected CT before review")
            previous_record = self._load_record(index["current"], cancelled=cancelled, deadline=deadline)
            previous = SeedAxisReconstruction.from_dict(previous_record["reconstruction"])
            if auth.image_ref != previous.image_ref:
                raise ImplantServiceError("implant_input_changed", "Review authorization names a different CT image revision")
            if self.image_fence is not None and not self.image_fence(previous.image_ref):
                raise ImplantServiceError("implant_input_changed", "The captured image changed before human review publication")
            reconstruction = review_observations(previous, request.decisions, reviewer_id=auth.reviewer_id,
                                                 coverage_status=request.coverage_status,
                                                 set_review_evidence=request.set_review_evidence)
            record = self._envelope(reconstruction, previous_record["artifacts"],
                                    previous_record["preoperative_timepoint_id"], previous_record["request_id"])
            check_execution(cancelled, deadline)
            self._publish(index, record, auth.expected_revision_id)
            self._hydrate_memory(index, record)
            return self._receipt(record, index)

    def _receipt(self, record, index):
        return {"record": copy.deepcopy(record), "current_revision_id": index["current"]["revision_id"],
                "is_current": _same_revision(record["reconstruction"]["revision_id"], index["current"]["revision_id"]),
                "generation": index["generation"], "memory_key": IMPLANT_MEMORY_KEY,
                "publication": "durable_owned_implant_journal", "clinical_use_ready": False}

    def correct(self, request: ImplantCorrectionRequest, *, cancelled=None, deadline=None):
        """Revise immutable observations with CAS and retry-safe correction receipts."""
        if not isinstance(request, ImplantCorrectionRequest):
            raise ImplantServiceError("implant_review_authorization_required", "Use a typed authenticated correction request")
        auth = request.authorization
        if (auth.owner_id, auth.image_ref.session_id, auth.image_ref.timepoint_id) != (
                self.scope.owner_id, self.scope.session_id, self.scope.timepoint_id):
            raise ImplantServiceError("invalid_implant_scope", "Correction scope does not match")
        signature = hashlib.sha256(_encoded(asdict(request))).hexdigest()
        with self._journal(cancelled=cancelled, deadline=deadline) as index:
            previous_job = index["jobs"].get(request.request_id)
            if previous_job is not None:
                if previous_job.get("input_signature") != signature or previous_job.get("operation") != "correction":
                    raise ImplantServiceError("implant_request_conflict", "Correction request ID is already bound")
                record = self._load_record(previous_job["revision"])
                self._hydrate_memory(index, self._load_record(index["current"]))
                return self._receipt(record, index)
            self._cas(index, auth.expected_revision_id)
            if len(index["jobs"]) >= self._limits().max_jobs:
                raise ImplantServiceError("implant_job_limit", "The observation request journal is full")
            previous_record = self._load_record(index["current"])
            previous = SeedAxisReconstruction.from_dict(previous_record["reconstruction"])
            if auth.image_ref != previous.image_ref or self.image_fence is not None and not self.image_fence(auth.image_ref):
                raise ImplantServiceError("implant_input_changed", "The correction's image is no longer current")
            by_id = {item.observation_id: item for item in previous.observations}
            if not set(request.observation_ids) <= set(by_id):
                raise ImplantServiceError("implant_observation_not_found", "Correction target is absent from this revision")
            if request.center_lps_mm is not None:
                import numpy as np
                voxel = previous.image_ref.geometry.xyz_from_points(np.asarray(request.center_lps_mm))
                if np.any(voxel < -.5) or np.any(voxel > np.asarray(previous.image_ref.geometry.size_xyz) - .5):
                    raise ImplantServiceError("implant_center_outside_image", "Correction center is outside the captured CT")
                if request.action == "add" and any(np.linalg.norm(np.asarray(item.center_lps_mm) - request.center_lps_mm) < .01
                        for item in previous.observations if item.review_status != "rejected"):
                    raise ImplantServiceError("implant_duplicate_center", "A detection already exists at this position")
            decisions = [ObservationReview(by_id[key].detection_id,
                "rejected" if request.action == "exclude" else "review_needed",
                "Human excluded a false-positive observation" if request.action == "exclude" else
                    "Human corrected or restored an observation; geometry requires review",
                corrected_center_lps_mm=request.center_lps_mm if request.action == "move" else None)
                for key in request.observation_ids]
            revised = review_observations(previous, decisions, reviewer_id=auth.reviewer_id,
                coverage_status="unknown")
            rows = list(revised.observations)
            # The supplied provider's directions depend on centers/line clusters.
            # Do not carry stale estimated axes into accepted dose inputs.
            rows = [replace(item, axis_lps=None, axis_source="unknown", review_status="review_needed",
                        reviewer_id=None, review_evidence=None, candidate_line_ids=(),
                        presentation=seed_presentation("review_needed", False, item.dimensions is not None),
                        diagnostics=item.diagnostics + ("correction_invalidated_provider_axis",))
                    if item.axis_source in {"provider_estimate", "estimated_from_deposition_line", "local_pca_with_line_prior"}
                        and item.review_status != "rejected" else replace(item, candidate_line_ids=()) for item in rows]
            if request.action == "add":
                identifier = str(uuid4())
                rows.append(SeedObservation(identifier, "manual_" + identifier, request.center_lps_mm, None, "unknown",
                    AxisDiagnostics(flags=("human_added_center_axis_unconfirmed",)), (), (),
                    ("human_added_detection",), seed_presentation("review_needed", False),
                    dimensions=None, review_status="review_needed", center_uncertainty_mm=None))
            revised = replace(revised, observations=tuple(rows), deposition_lines=(), coverage_status="unknown")
            record = self._envelope(revised, previous_record["artifacts"], previous_record["preoperative_timepoint_id"], previous_record["request_id"])
            record["correction"] = {"request_id": request.request_id, "action": request.action,
                "observation_ids": list(request.observation_ids), "reviewer_id": auth.reviewer_id,
                "source_revision_id": auth.expected_revision_id, "artifact_geometry_current": False}
            index["jobs"][request.request_id] = {"operation": "correction", "status": "running",
                "input_signature": signature, "started_at": _utc_now()}
            self._publish(index, record, auth.expected_revision_id, request_id=request.request_id)
            self._hydrate_memory(index, record)
            return self._receipt(record, index)


def execute_implant_tool(service, action, kwargs):
    """Shared bridge; BaseTool retains its normal result/error/timing conventions."""
    from tool_factory import ToolResult
    if not isinstance(service, ImplantService):
        return ToolResult(success=False, error="Bind an authenticated ImplantService for the captured timepoint; "
                          "configure BRACHYBOT_SEEDFINDER_BUNDLE and BRACHYBOT_SEEDFINDER_PYTHON for reconstruction.",
                          metadata={"code": "implant_service_not_bound", "clinical_use_ready": False})
    allowed = {"method", "action", "implant_service", "implant_input", "request_id", "expected_revision_id",
               "revision_id", "review_request"}
    if set(kwargs) - allowed:
        return ToolResult(success=False, error="SeedFinder actions accept only captured implant inputs and revision fields; "
                          "preoperative seed lists/axes and legacy threshold arguments are not used.",
                          metadata={"code": "invalid_implant_arguments"})
    try:
        if action == "reconstruct":
            receipt = service.reconstruct(kwargs.get("implant_input"), request_id=kwargs.get("request_id"),
                                          expected_revision_id=kwargs.get("expected_revision_id"), cancelled=is_cancelled)
        elif action == "get_reconstruction":
            receipt = service.get(revision_id=kwargs.get("revision_id"), cancelled=is_cancelled)
        elif action == "review_reconstruction":
            receipt = service.review(kwargs.get("review_request"), cancelled=is_cancelled)
        else:
            raise ImplantServiceError("invalid_implant_action", "Unknown reconstruction action")
        record = receipt["record"]
        revision = record["reconstruction"]
        counts = record["counts"]
        return ToolResult(success=True, data=revision["observations"],
                          message=f"Implant observations saved: {counts['detected_count']} detections, "
                                  f"{counts['accepted_count']} reviewed, {counts['review_needed_count']} need review. "
                                  "Clinical acceptance is not established.",
                          metadata={"method": "seedfinder", "implant_receipt": receipt,
                                    "implanted_seed_reconstruction": revision,
                                    "captured_image_ref": revision["image_ref"],
                                    "image_sha256": revision["image_ref"]["image_sha256"],
                                    "review_required": revision["review_status"] != "accepted",
                                    "baseline_accepted": False,
                                    "observation_revision_id": revision["revision_id"], "review_status": revision["review_status"],
                                    "counts": counts, "detected_seeds": revision["observations"],
                                    "num_detected": counts["detected_count"], "clinical_use_ready": False,
                                    "original_grid_mask_artifact": next(x for x in record["artifacts"] if x["role"] == "original_grid_mask")})
    except ReconstructionCancelled as exc:
        raise OperationCancelled(str(exc)) from exc
    except ImplantServiceError as exc:
        return ToolResult(success=False, error=str(exc), metadata={"code": exc.code, "clinical_use_ready": False})
    except (ValueError, OSError, RuntimeError) as exc:
        return ToolResult(success=False, error=str(exc), metadata={"code": "implant_operation_failed",
                          "clinical_use_ready": False, "recovery_action": "get_reconstruction"})
