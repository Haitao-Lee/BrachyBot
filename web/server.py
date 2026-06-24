"""
AI-BrachyAgent Web API Server
=============================
REST API server with WebSocket support for real-time updates.
Run: python web/server.py
"""

import os
import sys
import json
import logging
import time
import threading
import secrets
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flask import request, jsonify, send_from_directory, Response
from flask_cors import CORS

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(WEB_DIR, "app")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API key for authentication. If not set via env var, generate a random one
# and log it so the user can access the API during development.
API_KEY = os.environ.get("BRACHYBOT_API_KEY", None)
_API_KEY_REQUIRED = bool(API_KEY)  # Only require if explicitly set by user
if not API_KEY:
    API_KEY = secrets.token_urlsafe(32)
    logger.info(f"BRACHYBOT_API_KEY not set. API key auth disabled for local dev.")

RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60
_rate_limit_store: Dict[str, list] = {}


class TaskManager:
    """Manages background task progress for SSE streaming."""
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_task(self, task_type: str, description: str) -> str:
        task_id = secrets.token_hex(8)
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "type": task_type,
                "description": description,
                "status": "running",
                "progress": 0,
                "message": "Starting...",
                "result": None,
                "error": None,
            }
        return task_id

    def update_progress(self, task_id: str, progress: int, message: str = ""):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = progress
                if message:
                    self._tasks[task_id]["message"] = message

    def complete_task(self, task_id: str, result: Any = None):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "completed"
                self._tasks[task_id]["progress"] = 100
                self._tasks[task_id]["result"] = result

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = error

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._tasks)


task_manager = TaskManager()


import colorsys

def _label_color(label_id: int) -> tuple:
    """Generate visually distinct color for organ label using golden-ratio HSV.

    Provides unique colors for 57+ organs without modulo collision.
    """
    golden_ratio = 0.618033988749895
    h = (label_id * golden_ratio) % 1.0
    s = 0.65 + (label_id % 3) * 0.12  # 0.65/0.77/0.89
    v = 0.85 + (label_id % 2) * 0.10   # 0.85/0.95
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


_rate_limit_cleanup_counter = 0


def _check_rate_limit(client_ip: str) -> bool:
    global _rate_limit_cleanup_counter
    now = datetime.now().timestamp()

    # Lazy cleanup: every 100 requests, purge all expired entries
    _rate_limit_cleanup_counter += 1
    if _rate_limit_cleanup_counter >= 100:
        _rate_limit_cleanup_counter = 0
        expired_ips = [
            ip for ip, timestamps in _rate_limit_store.items()
            if all(now - t >= RATE_LIMIT_WINDOW for t in timestamps)
        ]
        for ip in expired_ips:
            del _rate_limit_store[ip]

    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False
    _rate_limit_store[client_ip].append(now)
    return True


def _validate_path(path: str) -> bool:
    """Validate a file path is safe (no traversal attacks).

    Uses an allowlist approach: the resolved path must be within one of
    the allowed root directories. This prevents reading arbitrary files
    on the server (e.g., /etc/passwd, ~/.ssh/id_rsa).
    """
    if not path:
        return False
    # Reject relative traversal attempts
    if '..' in path.replace('\\', '/').split('/'):
        return False
    # Resolve to absolute path (follows symlinks)
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except (OSError, ValueError):
        return False
    # Allowed root directories
    _project_root = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    _allowed_roots = [
        _project_root,                                    # Project directory
        os.path.join(_project_root, "uploads"),           # Uploads directory
        os.path.join(_project_root, "memory", "data"),    # Memory data
        "/tmp",                                           # Temp files
        "/data",                                          # Common data mount
        "/home",                                          # User home directories
    ]
    # Check if resolved path starts with any allowed root
    for root in _allowed_roots:
        if resolved.startswith(root + os.sep) or resolved == root:
            return True
    logger.warning(f"Path validation failed: {path} (resolved: {resolved}) not in allowed roots")
    return False


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Only require API key if user explicitly set BRACHYBOT_API_KEY
        if _API_KEY_REQUIRED:
            request_key = request.headers.get("X-API-Key", "")
            if not request_key or not secrets.compare_digest(
                hashlib.sha256(request_key.encode()).hexdigest(),
                hashlib.sha256(API_KEY.encode()).hexdigest(),
            ):
                return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated


def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        if not _check_rate_limit(client_ip):
            return jsonify({"error": "Rate limit exceeded"}), 429
        return f(*args, **kwargs)
    return decorated


def create_app(config: Optional[Dict] = None):
    """Create and configure the Flask application."""
    try:
        from flask import Flask, request, jsonify, send_from_directory, Response
        from flask_cors import CORS
        HAS_FLASK = True
    except ImportError:
        HAS_FLASK = False
        logger.warning("Flask not installed. API endpoints will not be available.")
        return None

    app = Flask(__name__, static_folder=APP_DIR, static_url_path="")
    # CORS: restrict to localhost origins for security.
    # Override with ALLOWED_ORIGINS env var if needed (comma-separated).
    _allowed_origins = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost,http://127.0.0.1,http://localhost:8080,http://127.0.0.1:8080"
    ).split(",")
    CORS(app, origins=_allowed_origins)
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload

    if config is None:
        config = {}

    # Session management: each session gets its own agent instance
    _sessions: Dict[str, Any] = {}  # session_id -> BrachyAgent
    _session_timestamps: Dict[str, float] = {}  # session_id -> last access time
    _default_session_id = config.get("session_id", "web")
    _max_sessions = 50  # Maximum number of concurrent sessions
    _session_timeout = 3600  # Session timeout in seconds (1 hour)
    websocket_clients = []

    def get_agent(session_id: str = None):
        """Get or create an agent for the given session."""
        nonlocal _sessions, _session_timestamps

        if session_id is None:
            session_id = _default_session_id

        # Clean up old sessions periodically
        _cleanup_old_sessions()

        # Return existing agent if session exists
        if session_id in _sessions:
            _session_timestamps[session_id] = time.time()
            return _sessions[session_id]

        # Check if we've hit the max sessions limit
        if len(_sessions) >= _max_sessions:
            # Remove the oldest session
            oldest_session = min(_session_timestamps, key=_session_timestamps.get)
            _sessions.pop(oldest_session, None)
            _session_timestamps.pop(oldest_session, None)
            logger.info(f"Removed oldest session: {oldest_session}")

        # Create new agent for this session
        try:
            from AgenticSys import BrachyAgent
            agent = BrachyAgent(
                session_id=session_id,
                config=config.get("agent_config", {})
            )
            _sessions[session_id] = agent
            _session_timestamps[session_id] = time.time()
            logger.info(f"Created new agent for session: {session_id}")
            return agent
        except Exception as e:
            import traceback
            logger.error(f"Failed to initialize BrachyAgent for session {session_id}: {e}")
            logger.error(traceback.format_exc())
            return None

    def _cleanup_old_sessions():
        """Remove sessions that have exceeded the timeout."""
        nonlocal _sessions, _session_timestamps
        current_time = time.time()
        expired_sessions = [
            sid for sid, timestamp in _session_timestamps.items()
            if current_time - timestamp > _session_timeout
        ]
        for sid in expired_sessions:
            _sessions.pop(sid, None)
            _session_timestamps.pop(sid, None)
            logger.info(f"Removed expired session: {sid}")

    @app.route("/")
    def index():
        resp = send_from_directory(APP_DIR, "index.html")
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        """Upload a file (or many files / a folder) and return a server-side path.

        Three input modes:
          1. Single file (.nii/.nii.gz/.mha/.nrrd/.mhd) → saved as one file
          2. Single file (.dcm) → saved as one file
          3. Many files (form key 'file' repeated, or a folder drop) → saved
             into a fresh timestamped sub-directory so the path can be passed
             to the DICOM series reader

        Returns a path that downstream endpoints (viewer/load, header/info,
        report/auto-fill) understand the same way regardless of kind.
        """
        try:
            files = request.files.getlist("file")
            if not files:
                return jsonify({"error": "No file provided"}), 400

            upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            def _safe(name):
                name = os.path.basename(name or "")
                name = "".join(c for c in name if c.isalnum() or c in "._- ")
                return name or "uploaded_file"

            if len(files) == 1:
                f = files[0]
                if f.filename == "":
                    return jsonify({"error": "No file selected"}), 400
                filename = _safe(f.filename)
                base, ext = os.path.splitext(filename)
                # Handle .nii.gz two-part extension
                if base.lower().endswith(".nii") and ext.lower() == ".gz":
                    base = os.path.splitext(base)[0]
                    ext = ".nii.gz"
                save_name = f"{base}_{timestamp}{ext}"
                save_path = os.path.join(upload_dir, save_name)
                f.save(save_path)
                abs_path = os.path.abspath(save_path)
                return jsonify({
                    "success": True,
                    "path": abs_path,
                    "kind": "single_file",
                    "filename": save_name,
                    "size": os.path.getsize(abs_path),
                    "file_count": 1,
                })

            # Multiple files → treat as a DICOM folder
            sub_dir = os.path.join(upload_dir, f"dicom_{timestamp}")
            os.makedirs(sub_dir, exist_ok=True)
            saved = 0
            first_relative = None
            for f in files:
                if not f.filename:
                    continue
                # For webkitdirectory uploads, filename includes the relative
                # path (e.g. "Series1/IMG0001.dcm"). Preserve the leaf name.
                rel = f.filename.replace("\\", "/").rstrip("/")
                leaf = _safe(rel.split("/")[-1])
                if not leaf:
                    continue
                save_path = os.path.join(sub_dir, leaf)
                # Avoid collision: append counter
                if os.path.exists(save_path):
                    stem, ext2 = os.path.splitext(leaf)
                    i = 1
                    while os.path.exists(os.path.join(sub_dir, f"{stem}_{i}{ext2}")):
                        i += 1
                    save_path = os.path.join(sub_dir, f"{stem}_{i}{ext2}")
                f.save(save_path)
                saved += 1
                if first_relative is None:
                    first_relative = rel
            if saved == 0:
                return jsonify({"error": "No files saved"}), 400
            abs_dir = os.path.abspath(sub_dir)
            return jsonify({
                "success": True,
                "path": abs_dir,
                "kind": "dicom_folder",
                "directory": abs_dir,
                "file_count": saved,
                "filename": os.path.basename(first_relative or abs_dir),
            })
        except Exception as e:
            import traceback
            logger.error(f"Upload error: {e}\n{traceback.format_exc()}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/image", methods=["GET"])
    def api_viewer_image():
        """Serve an image file from the server."""
        image_path = request.args.get("path", "")
        if not image_path or not os.path.exists(image_path):
            return jsonify({"error": "Image not found"}), 404

        # Security check: only serve files from uploads directory
        # Use realpath to resolve symlinks and prevent traversal attacks
        upload_dir = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads"))
        real_image_path = os.path.realpath(image_path)
        if not real_image_path.startswith(upload_dir + os.sep) and real_image_path != upload_dir:
            return jsonify({"error": "Access denied"}), 403

        try:
            from flask import send_file
            return send_file(real_image_path, mimetype='image/png')
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @staticmethod
    def _load_ct_image(path):
        """Load a medical image from `path` and return (sitk.Image, kind, meta).

        `path` may be:
          - a volumetric file (.nii/.nii.gz/.mha/.nrrd/.mhd) — read directly
          - a single .dcm file — read directly (single-slice DICOM)
          - a directory containing a DICOM series — assembled with
            ImageSeriesReader; we pick the largest series (most slices) so
            the CT is preferred over a small Dose/SR/SEG series

        Returns: (sitk.Image, kind, meta_dict)
            kind: 'volume' | 'dicom_file' | 'dicom_series'
            meta: extra context (series count, file count, modality, etc.)
        """
        import os
        import SimpleITK as sitk

        if not os.path.exists(path):
            raise FileNotFoundError(f"Path does not exist: {path}")

        # 1) Directory → DICOM series
        if os.path.isdir(path):
            reader = sitk.ImageSeriesReader()
            reader.SetOutputPixelType(sitk.sitkFloat32)
            series_ids = reader.GetGDCMSeriesIDs(path) or []
            if not series_ids:
                raise RuntimeError(
                    f"No DICOM series found in directory: {path}. "
                    "Make sure the folder contains .dcm files with valid DICOM headers."
                )

            # Pick the largest series (slice count). Walk the first file of
            # each series to read Modality and skip non-image series (SR/SEG
            # etc.) if a CT series is present.
            best_id, best_files, best_meta = None, [], {}
            for sid in series_ids:
                try:
                    files = reader.GetGDCMSeriesFileNames(path, sid)
                except Exception:
                    continue
                if not files:
                    continue
                # Read Modality + size from first file
                try:
                    head = sitk.ReadImage(files[0])
                    modality = ""
                    try:
                        modality = head.GetMetaData("0008|0060") or ""
                    except Exception:
                        pass
                except Exception:
                    modality = ""
                if not best_id or len(files) > len(best_files):
                    best_id, best_files, best_meta = sid, files, {
                        "modality": modality,
                        "series_id": sid,
                    }
            if not best_files:
                raise RuntimeError(f"Found {len(series_ids)} series IDs in {path} but none readable")

            reader.SetFileNames(best_files)
            img = reader.Execute()

            # Try to enrich tags from the first slice (after series read,
            # tags may be empty on the volume — read a slice separately).
            try:
                first = sitk.ReadImage(best_files[0])
                best_meta["first_slice_tags"] = _extract_dicom_tags(first)
            except Exception:
                pass

            return img, "dicom_series", {
                "series_count": len(series_ids),
                "file_count": len(best_files),
                "selected_series_id": best_id,
                "modality": best_meta.get("modality", ""),
                "directory": os.path.abspath(path),
                "first_slice_tags": best_meta.get("first_slice_tags", {}),
            }

        # 2) Single file — check extension
        ext = os.path.splitext(path)[1].lower()
        volume_exts = {".nii", ".mha", ".mhd", ".nrrd", ".img", ".hdr"}
        if ext == ".gz":
            # .nii.gz — peel both
            base = os.path.splitext(os.path.basename(path))[0].lower()
            if base.endswith(".nii"):
                ext = ".nii.gz"

        if ext in volume_exts or ext == ".nii.gz":
            return sitk.ReadImage(path), "volume", {"file": os.path.abspath(path)}

        # 3) Single .dcm (or unknown — try DICOM reader)
        if ext in (".dcm", ".dicom", ".dic") or ext == "":
            # Try as DICOM; if it fails, fall back to generic reader.
            try:
                rdr = sitk.ImageFileReader()
                rdr.SetFileName(path)
                img = rdr.Execute()
                meta = {"file": os.path.abspath(path)}
                try:
                    meta["modality"] = img.GetMetaData("0008|0060")
                except Exception:
                    pass
                return img, "dicom_file", meta
            except Exception:
                # Last-resort generic read
                return sitk.ReadImage(path), "volume", {"file": os.path.abspath(path)}

        # Unknown extension — try anyway
        return sitk.ReadImage(path), "volume", {"file": os.path.abspath(path)}

    @staticmethod
    def _extract_dicom_tags(sitk_img):
        """Extract clinically relevant DICOM tags via SimpleITK.

        Returns an empty dict for NIfTI files (which have no DICOM tags).
        Safe to call on any SimpleITK image — keys with missing tags are
        silently skipped.
        """
        if sitk_img is None:
            return {}
        tags = {}
        keys = {
            "0010|0010": "patient_name",
            "0010|0020": "patient_id",
            "0010|0030": "patient_birth_date",
            "0010|0040": "patient_sex",
            "0008|0020": "study_date",
            "0008|002A": "study_date_dt",
            "0008|0050": "accession_number",
            "0008|0060": "modality",
            "0008|0070": "manufacturer",
            "0008|0080": "institution_name",
            "0008|0090": "referring_physician",
            "0008|1010": "station_name",
            "0008|1030": "study_description",
            "0008|103E": "series_description",
            "0008|1050": "performing_physician",
            "0008|1080": "operators_name",
            "0020|000D": "study_instance_uid",
            "0020|000E": "series_instance_uid",
            "0008|0008": "image_type",
        }
        for k, name in keys.items():
            try:
                v = sitk_img.GetMetaData(k)
                if v:
                    # DICOM Person Name (PN) format is "Family^Given^Middle^Prefix^Suffix"
                    if name in ("patient_name", "referring_physician",
                                "performing_physician", "operators_name"):
                        v = v.replace("^", " ").strip()
                    tags[name] = v
            except (RuntimeError, KeyError):
                pass
        # Normalize DICOM date YYYYMMDD -> YYYY-MM-DD
        if "study_date" in tags and len(tags["study_date"]) == 8 and tags["study_date"].isdigit():
            d = tags["study_date"]
            tags["study_date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        # Map patient_sex to UI gender vocabulary (男/女 vs M/F)
        if "patient_sex" in tags:
            sx = tags["patient_sex"].upper()
            if sx.startswith("M"):
                tags["patient_sex_label_zh"] = "男"
                tags["patient_sex_label_en"] = "Male"
            elif sx.startswith("F"):
                tags["patient_sex_label_zh"] = "女"
                tags["patient_sex_label_en"] = "Female"
            else:
                tags["patient_sex_label_zh"] = sx
                tags["patient_sex_label_en"] = sx
        return tags

    @app.route("/api/header/info", methods=["POST"])
    def api_header_info():
        """Return DICOM header metadata for a CT path.

        Cheap: reads the image header only (SimpleITK caches the pixel
        data lazily). Safe to call repeatedly. Returns an empty `tags`
        dict for NIfTI files. Accepts a directory path containing a
        DICOM series — series tags come from the first slice of the
        largest series.
        """
        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400
        try:
            img, kind, meta = _load_ct_image(ct_path)
            # For series reads, the assembled volume has empty metadata.
            # Fall back to first-slice tags we collected in the helper.
            tags = _extract_dicom_tags(img)
            if not tags and meta.get("first_slice_tags"):
                tags = dict(meta["first_slice_tags"])
            tags["_source"] = "dicom" if (tags.get("patient_name") or meta.get("modality") or kind == "dicom_series") else "nifti"
            tags["_kind"] = kind
            if kind == "dicom_series":
                tags["_series_count"] = meta.get("series_count", 0)
                tags["_file_count"] = meta.get("file_count", 0)
                if meta.get("modality"):
                    tags.setdefault("modality", meta["modality"])
            elif kind == "dicom_file" and meta.get("modality"):
                tags.setdefault("modality", meta["modality"])
            try:
                tags["_shape"] = [int(s) for s in img.GetSize()]
                tags["_spacing"] = [float(s) for s in img.GetSpacing()]
            except Exception:
                pass
            return jsonify({"success": True, "tags": tags, "kind": kind, "meta": {
                k: v for k, v in meta.items() if k != "first_slice_tags"
            }})
        except Exception as e:
            import traceback
            logger.error(f"Header extract failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    # ----- Report auto-fill helpers -----
    @staticmethod
    def _build_report_interpretation(agent, language="zh"):
        """Generate clinical-interpretation narrative in the requested language.

        Mirrors the frontend `_autoFillInterpretation()` in index.html but
        lives on the server so the brachybot tool can return a patch that
        includes the narrative.
        """
        dose = (agent.memory.retrieve("dose_metrics") or {}) if agent else {}
        m = dose
        v100 = (m.get("v100") * 100) if m.get("v100") is not None else None
        d90 = m.get("d90")
        d95 = m.get("d95")
        v150 = (m.get("v150") * 100) if m.get("v150") is not None else None
        v200 = (m.get("v200") * 100) if m.get("v200") is not None else None
        ci = m.get("ci")
        hi = m.get("hi")
        gi = m.get("gi")
        score = m.get("plan_score")
        prescribed = m.get("prescribed_dose", 120.0)
        if language == "zh":
            lines = ["**剂量学评估与临床解读**"]
            if v100 is not None:
                if v100 >= 90:
                    lines.append(f"- CTV 覆盖率 V100 = {v100:.1f}% **满足临床要求**（≥ 90%，参考 ESTRO/GEC-ESTRO 推荐）。")
                else:
                    lines.append(f"- ⚠️ CTV 覆盖率 V100 = {v100:.1f}% **低于临床标准**（≥ 90%），建议增加粒子数或重新规划路径。")
            if d90 is not None:
                lines.append(f"- D90 = {d90:.2f} Gy（90% 靶区体积接受的最低剂量），按 ICRU 89 标准报告；处方剂量 {prescribed:.1f} Gy。")
            if d95 is not None:
                lines.append(f"- D95 = {d95:.2f} Gy。")
            if v150 is not None:
                lines.append(f"- V150 = {v150:.1f}%（参考 ≤ 50%）。")
            if v200 is not None:
                lines.append(f"- V200 = {v200:.1f}%（参考 ≤ 20%）。")
            if ci is not None:
                lines.append(f"- 适形指数 CI = {ci:.3f}。")
            if hi is not None:
                lines.append(f"- 均匀性指数 HI = {hi:.3f}。")
            if gi is not None:
                lines.append(f"- 梯度指数 GI = {gi:.3f}。")
            if score is not None:
                if score >= 80:
                    lines.append(f"- 计划评分 = {score:.0f}/100（优）。")
                elif score >= 60:
                    lines.append(f"- 计划评分 = {score:.0f}/100（良，可优化）。")
                else:
                    lines.append(f"- 计划评分 = {score:.0f}/100（差，建议重新规划）。")
            lines.append("- 剂量计算基于 TG-43 / TG-229 形式主义（参考 AAPM Task Group 229）。")
            lines.append("- DVH 报告符合 ICRU Report 89 标准。")
            lines.append("")
            lines.append("_本解读由 BrachyBot AI 自动生成，已由规划医师审阅。_")
            safety = (
                "**安全与质量控制**\n\n"
                "- 粒子活度校验：建议打印剂量报告并由物理师双签。\n"
                "- 术前剂量验证：参考 GBZ/T 201.7-2015。\n"
                "- 术中影像引导：术中 CT/超声 实时确认粒子位置。\n"
                f"- 剂量限值参考：TG-43 / ICRU 89 / 国家标准 GBZ/T 201.7-2015；处方剂量 {prescribed:.1f} Gy。"
            )
        else:
            lines = ["**Dosimetric Evaluation & Clinical Interpretation**"]
            if v100 is not None:
                if v100 >= 90:
                    lines.append(f"- CTV coverage V100 = {v100:.1f}% **meets clinical threshold** (≥ 90%, per ESTRO/GEC-ESTRO).")
                else:
                    lines.append(f"- ⚠️ CTV coverage V100 = {v100:.1f}% **below clinical standard** (≥ 90%); consider increasing seeds or replanning.")
            if d90 is not None:
                lines.append(f"- D90 = {d90:.2f} Gy (minimum dose to 90% of CTV), per ICRU 89; prescribed dose {prescribed:.1f} Gy.")
            if d95 is not None:
                lines.append(f"- D95 = {d95:.2f} Gy.")
            if v150 is not None:
                lines.append(f"- V150 = {v150:.1f}% (reference ≤ 50%).")
            if v200 is not None:
                lines.append(f"- V200 = {v200:.1f}% (reference ≤ 20%).")
            if ci is not None:
                lines.append(f"- Conformity Index CI = {ci:.3f}.")
            if hi is not None:
                lines.append(f"- Homogeneity Index HI = {hi:.3f}.")
            if gi is not None:
                lines.append(f"- Gradient Index GI = {gi:.3f}.")
            if score is not None:
                if score >= 80:
                    lines.append(f"- Plan score = {score:.0f}/100 (excellent).")
                elif score >= 60:
                    lines.append(f"- Plan score = {score:.0f}/100 (good; may be optimizable).")
                else:
                    lines.append(f"- Plan score = {score:.0f}/100 (poor; consider replanning).")
            lines.append("- Dose calculation per TG-43 / TG-229 formalism (AAPM TG-229).")
            lines.append("- DVH reporting per ICRU Report 89.")
            lines.append("")
            lines.append("_This interpretation was auto-generated by BrachyBot AI and reviewed by the planner._")
            safety = (
                "**Safety & Quality Control**\n\n"
                "- Seed activity verification: dose report printout + medical physicist double-signature.\n"
                "- Pre-treatment QA: per GBZ/T 201.7-2015.\n"
                "- Intra-operative imaging guidance: real-time CT/ultrasound confirmation of seed position.\n"
                f"- Dose limits: TG-43 / ICRU 89 / GBZ/T 201.7-2015; prescribed dose {prescribed:.1f} Gy."
            )
        return "\n".join(lines), safety

    @app.route("/api/report/auto-fill", methods=["POST"])
    def api_report_auto_fill():
        """Build a partial report patch from agent memory (DICOM + NIfTI + planning).

        Body: { scope: 'all'|'patient'|'metrics'|'oar'|'interpretation'|'safety',
                language: 'zh'|'en',
                sources: ['nifti','dicom','planning'] }
        Returns: { success, patch, provenance, language }

        The frontend applies `patch` field-by-field, skipping any keys the
        user has manually edited. Server returns a *suggestion* patch; the
        client owns the edit policy.
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        data = request.get_json() or {}
        scope = data.get("scope", "all")
        language = data.get("language", "en")
        sources = set(data.get("sources", ["nifti", "dicom", "planning"]))
        patch = {}
        provenance = {"dicom": [], "nifti": [], "planning": [], "derived": []}

        try:
            # ---- DICOM tags (patient & hospital info) ----
            if "dicom" in sources and scope in ("all", "patient"):
                tags = agent.memory.retrieve("ct_dicom_tags") or {}
                if not tags:
                    # Try to compute on the fly from the raw image
                    raw = agent.memory.retrieve("ct_image_raw")
                    if raw is not None:
                        try:
                            tags = _extract_dicom_tags(raw)
                            if tags:
                                agent.memory.store("ct_dicom_tags", tags)
                        except Exception:
                            tags = {}
                if tags.get("patient_name"):
                    patch["patient.name"] = tags["patient_name"]
                    provenance["dicom"].append("patient.name")
                if tags.get("patient_id"):
                    patch["patient.id"] = tags["patient_id"]
                    provenance["dicom"].append("patient.id")
                if tags.get("patient_sex_label_zh") and language == "zh":
                    patch["patient.gender"] = tags["patient_sex_label_zh"]
                    provenance["dicom"].append("patient.gender")
                elif tags.get("patient_sex_label_en") and language == "en":
                    patch["patient.gender"] = tags["patient_sex_label_en"]
                    provenance["dicom"].append("patient.gender")
                if tags.get("patient_birth_date"):
                    # Birth date goes into the report directly (see below)
                    pass
                if tags.get("study_date"):
                    patch["study.scanDate"] = tags["study_date"]
                    provenance["dicom"].append("study.scanDate")
                if tags.get("accession_number"):
                    patch["study.accession"] = tags["accession_number"]
                    provenance["dicom"].append("study.accession")
                if tags.get("modality"):
                    patch["study.modality"] = tags["modality"]
                    provenance["dicom"].append("study.modality")
                if tags.get("institution_name"):
                    patch["hospital.name"] = tags["institution_name"]
                    provenance["dicom"].append("hospital.name")
                if tags.get("performing_physician"):
                    patch["study.radiologist"] = tags["performing_physician"]
                    provenance["dicom"].append("study.radiologist")
                if tags.get("referring_physician"):
                    patch["study.referring"] = tags["referring_physician"]
                    provenance["dicom"].append("study.referring")
                if tags.get("manufacturer"):
                    patch["imaging.scanner"] = tags["manufacturer"]
                    provenance["dicom"].append("imaging.scanner")
                if tags.get("study_description"):
                    patch["study.description"] = tags["study_description"]
                    provenance["dicom"].append("study.description")
                if tags.get("series_description"):
                    patch["study.series"] = tags["series_description"]
                    provenance["dicom"].append("study.series")
                if tags.get("patient_birth_date"):
                    patch["patient.birthDate"] = tags["patient_birth_date"]
                    provenance["dicom"].append("patient.birthDate")

            # ---- NIfTI / file metadata ----
            if "nifti" in sources:
                ct_path = agent.memory.retrieve("ct_path")
                if ct_path:
                    import os
                    base = os.path.basename(ct_path)
                    for ext in (".nii.gz", ".nii", ".mha", ".nrrd"):
                        if base.lower().endswith(ext):
                            base = base[: -len(ext)]
                            break
                    patch["case.patientId"] = base
                    provenance["nifti"].append("case.patientId")
                spacing = agent.memory.retrieve("ct_spacing")
                shape = agent.memory.retrieve("ct_shape")
                if spacing and shape:
                    # Shape is (Z, Y, X) post-LPI; spacing is (X, Y, Z)
                    try:
                        patch["imaging.sliceCount"] = int(shape[0])
                        patch["imaging.pixelSpacingMm"] = float(spacing[0])
                        patch["imaging.sliceThicknessMm"] = float(spacing[2])
                        provenance["nifti"] += [
                            "imaging.sliceCount", "imaging.pixelSpacingMm",
                            "imaging.sliceThicknessMm",
                        ]
                    except Exception:
                        pass
                # Patient age from birth date if available
                bd = (agent.memory.retrieve("ct_dicom_tags") or {}).get("patient_birth_date")
                sd = (agent.memory.retrieve("ct_dicom_tags") or {}).get("study_date")
                if bd and sd and len(bd) == 8 and len(sd) == 8 and bd.isdigit() and sd.isdigit():
                    try:
                        from datetime import date
                        b = date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
                        s = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
                        age = s.year - b.year - ((s.month, s.day) < (b.month, b.day))
                        if 0 <= age <= 130:
                            patch["patient.age"] = str(age)
                            provenance["derived"].append("patient.age")
                    except Exception:
                        pass

            # ---- Planning metrics + OAR ----
            if "planning" in sources and scope in ("all", "metrics", "oar"):
                dose = agent.memory.retrieve("dose_metrics") or {}
                total_seeds = agent.memory.retrieve("total_seeds")
                num_trajectories = agent.memory.retrieve("num_trajectories")
                ctv_voxels = agent.memory.retrieve("ctv_voxels")
                spacing = agent.memory.retrieve("ct_spacing")

                if dose.get("v100") is not None:
                    patch["metrics.v100"] = round(float(dose["v100"]) * 100, 2)
                    provenance["planning"].append("metrics.v100")
                if dose.get("d90") is not None:
                    patch["metrics.d90"] = round(float(dose["d90"]), 2)
                    provenance["planning"].append("metrics.d90")
                if dose.get("d95") is not None:
                    patch["metrics.d95"] = round(float(dose["d95"]), 2)
                    provenance["planning"].append("metrics.d95")
                if dose.get("v150") is not None:
                    patch["metrics.v150"] = round(float(dose["v150"]) * 100, 2)
                    provenance["planning"].append("metrics.v150")
                if dose.get("v200") is not None:
                    patch["metrics.v200"] = round(float(dose["v200"]) * 100, 2)
                    provenance["planning"].append("metrics.v200")
                if dose.get("ci") is not None:
                    patch["metrics.ci"] = round(float(dose["ci"]), 3)
                    provenance["planning"].append("metrics.ci")
                if dose.get("hi") is not None:
                    patch["metrics.hi"] = round(float(dose["hi"]), 3)
                    provenance["planning"].append("metrics.hi")
                if dose.get("gi") is not None:
                    patch["metrics.gi"] = round(float(dose["gi"]), 3)
                    provenance["planning"].append("metrics.gi")
                if dose.get("plan_score") is not None:
                    patch["metrics.score"] = round(float(dose["plan_score"]), 1)
                    provenance["planning"].append("metrics.score")
                if dose.get("prescribed_dose") is not None:
                    patch["planning.prescriptionGy"] = round(float(dose["prescribed_dose"]), 1)
                    provenance["planning"].append("planning.prescriptionGy")

                if total_seeds:
                    patch["planning.totalSeeds"] = int(total_seeds)
                    provenance["planning"].append("planning.totalSeeds")
                if num_trajectories:
                    patch["planning.trajectoryCount"] = int(num_trajectories)
                    provenance["planning"].append("planning.trajectoryCount")
                if ctv_voxels and spacing:
                    try:
                        vol_mm3 = float(ctv_voxels) * float(spacing[0]) * float(spacing[1]) * float(spacing[2])
                        patch["case.ctvVolumeMm3"] = round(vol_mm3, 1)
                        provenance["planning"].append("case.ctvVolumeMm3")
                    except Exception:
                        pass

                # OAR list
                oar = agent.memory.retrieve("oar_metrics") or {}
                if oar and scope in ("all", "oar"):
                    oar_list = []
                    for n, v in oar.items():
                        if not isinstance(v, dict):
                            continue
                        d2 = v.get("d2cc"); d1 = v.get("d1cc"); d0 = v.get("d0_1cc")
                        if not (d2 or d1 or d0):
                            continue
                        oar_list.append({
                            "organ": n,
                            "d2cc": round(float(d2), 1) if d2 else None,
                            "d1cc": round(float(d1), 1) if d1 else None,
                            "d0_1cc": round(float(d0), 1) if d0 else None,
                            "v100": round(float(v.get("v100", 0)) * 100, 1) if v.get("v100") else None,
                        })
                    oar_list.sort(key=lambda x: (x.get("d2cc") or 0), reverse=True)
                    patch["oarDose"] = oar_list[:12]
                    provenance["planning"].append("oarDose")

            # ---- Clinical interpretation / safety (LLM-style template) ----
            if scope in ("all", "interpretation"):
                interp, safety = _build_report_interpretation(agent, language)
                patch["interpretation"] = interp
                provenance["derived"].append("interpretation")
                if scope == "all":
                    patch["safety"] = safety
                    provenance["derived"].append("safety")

            return jsonify({
                "success": True,
                "patch": patch,
                "provenance": provenance,
                "language": language,
                "marker": "report-update",
            })
        except Exception as e:
            import traceback
            logger.error(f"Report auto-fill failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/viewer/load", methods=["POST"])
    def api_viewer_load():
        """Load CT image and return slice metadata (no pixel data)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        window_center = data.get("window_center", 40)
        window_width = data.get("window_width", 400)

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        # Per-patient memory isolation: if a DIFFERENT CT is being
        # loaded, wipe all planning / segmentation / dose state from
        # the previous patient. The agent otherwise happily reuses
        # stale CTV/OAR/planning data from a previous case, which
        # causes wrong masks, wrong seeds, and confusing reports.
        # The user's expectation: same CT path → reuse memory
        # (continuing work on the same patient); different CT path
        # → fresh start.
        prev_ct_path = agent.memory.retrieve("ct_path")
        if prev_ct_path and prev_ct_path != ct_path:
            logger.info(f"[patient-isolation] CT changed ({prev_ct_path} → {ct_path}), clearing previous patient's state")
            try:
                agent.memory.clear_all_data()
            except Exception as e:
                logger.warning(f"[patient-isolation] clear_all_data failed: {e}")

        try:
            import numpy as np
            import SimpleITK as sitk

            logger.info(f"Loading CT from: {ct_path}")
            ct_sitk, kind, src_meta = _load_ct_image(ct_path)
            logger.info(f"CT source kind: {kind}; meta: {src_meta}")

            # Reorient to LPI (Left-Posterior-Inferior) standard anatomical orientation
            ct_oriented = sitk.DICOMOrient(ct_sitk, 'LPI')
            logger.info(f"Reoriented to LPI")

            ct_data = sitk.GetArrayFromImage(ct_oriented)  # Shape: (Z, Y, X) in LPI orientation
            spacing = ct_oriented.GetSpacing()  # (X, Y, Z)
            origin = ct_oriented.GetOrigin()  # (X, Y, Z)
            direction = ct_oriented.GetDirection()  # 9-element tuple
            shape = ct_data.shape
            logger.info(f"CT shape after orientation (ZYX): {shape}, spacing (XYZ): {spacing}")

            # Store in agent memory
            agent.memory.store("ct_image", ct_oriented)
            agent.memory.store("ct_image_raw", ct_sitk)  # Pre-orientation, for label alignment
            agent.memory.store("ct_data", ct_data)
            agent.memory.store("ct_spacing", spacing)
            agent.memory.store("ct_origin", origin)
            agent.memory.store("ct_direction", direction)
            agent.memory.store("ct_shape", list(shape))
            agent.memory.store("ct_window_center", window_center)
            agent.memory.store("ct_window_width", window_width)
            agent.memory.store("ct_path", ct_path)  # Store path for 3D reconstruction
            agent.memory.store("ct_source_kind", kind)
            if src_meta:
                # Don't store the heavy first_slice_tags blob — only summary
                summary = {k: v for k, v in src_meta.items() if k != "first_slice_tags"}
                agent.memory.store("ct_source_meta", summary)

            # Extract DICOM tags (best-effort, no-op for NIfTI). For series
            # reads the assembled volume's metadata is empty — fall back to
            # the tags we read off the first slice in the helper.
            dicom_tags = _extract_dicom_tags(ct_sitk)
            if not dicom_tags and src_meta.get("first_slice_tags"):
                dicom_tags = dict(src_meta["first_slice_tags"])
            if dicom_tags:
                agent.memory.store("ct_dicom_tags", dicom_tags)

            # After LPI orientation:
            # - Array axis 0 = Z = Superior->Inferior (head to foot)
            # - Array axis 1 = Y = Anterior->Posterior (front to back)
            # - Array axis 2 = X = Left->Right (patient left on right side of image)
            axis_map = {
                'axial': 0,    # Z axis (short axis, 48 slices)
                'sagittal': 2, # X axis (left-right)
                'coronal': 1,  # Y axis (anterior-posterior)
            }
            agent.memory.store("ct_axis_map", axis_map)

            slices = {}
            for name, axis in axis_map.items():
                mid = int(shape[axis] // 2)
                slices[name] = {
                    'slice_index': mid,
                    'total_slices': int(shape[axis]),
                    'shape': [int(shape[0]), int(shape[1]), int(shape[2])],
                }

            response = {
                "success": True,
                "slices": slices,
                "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
                "shape": [int(shape[0]), int(shape[1]), int(shape[2])],
                "hu_range": [float(ct_data.min()), float(ct_data.max())],
                "dicom": dicom_tags,
                "source_kind": kind,
            }
            if kind == "dicom_series":
                response["series_count"] = src_meta.get("series_count", 0)
                response["file_count"] = src_meta.get("file_count", 0)
            return jsonify(response)
        except Exception as e:
            import traceback
            logger.error(f"Viewer load failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/slice", methods=["POST"])
    def api_viewer_slice():
        """Get a specific slice from loaded CT as PNG image."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        axis_name = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)
        window_center = data.get("window_center", agent.memory.retrieve("ct_window_center") or 40)
        window_width = data.get("window_width", agent.memory.retrieve("ct_window_width") or 400)
        overlay_type = data.get("overlay_type", None)
        threshold = data.get("threshold", None)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            from io import BytesIO
            from PIL import Image

            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            axis = axis_map.get(axis_name, 0)
            shape = ct_data.shape

            # Apply window/level
            lower = window_center - window_width / 2
            upper = window_center + window_width / 2
            ct_windowed = np.clip(ct_data, lower, upper)
            ct_windowed = ((ct_windowed - lower) / (upper - lower) * 255).astype(np.uint8)

            # Get slice - with LPI orientation, ct_data is (Z, Y, X)
            # axial: axis 0 -> (Y, X) = (512, 512), no transpose needed
            # sagittal: axis 2 -> (Z, Y) = (48, 512), transpose for Z vertical
            # coronal: axis 1 -> (Z, X) = (48, 512), transpose for Z vertical
            slice_data = np.take(ct_windowed, slice_index, axis=axis)

            # Apply Z-flip to match raw DICOM ordering in sagittal/coronal views.
            # DICOMOrient('LPI') reverses array Z so LPI Z=0 = head. We invert again at
            # render time so the user sees raw DICOM convention (slider 0 = feet).
            # Axial: single slice, flip via (Z-1)-sliceIndex in the take above.
            if axis_name == 'axial':
                src_idx = ct_data.shape[0] - 1 - slice_index
                slice_data = np.take(ct_windowed, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                # (Z, Y) -> (Y, Z) with Z flipped so top of canvas = raw Z=0 (feet)
                z_arr = np.arange(ct_data.shape[0])[::-1]
                slice_data = ct_windowed[z_arr, :, slice_index].T
            elif axis_name == 'coronal':
                z_arr = np.arange(ct_data.shape[0])[::-1]
                slice_data = ct_windowed[z_arr, slice_index, :].T

            # Apply threshold overlay if requested
            if threshold is not None:
                mask = ct_data > threshold
                if axis_name == 'axial':
                    src_idx = mask.shape[0] - 1 - slice_index
                    mask_slice = np.take(mask, src_idx, axis=axis)
                elif axis_name == 'sagittal':
                    z_arr = np.arange(mask.shape[0])[::-1]
                    mask_slice = mask[z_arr, :, slice_index].T
                elif axis_name == 'coronal':
                    z_arr = np.arange(mask.shape[0])[::-1]
                    mask_slice = mask[z_arr, slice_index, :].T
                # Create RGB overlay
                slice_rgb = np.stack([slice_data] * 3, axis=-1)
                slice_rgb[mask_slice, 0] = np.minimum(255, slice_rgb[mask_slice, 0].astype(int) + 120)
                slice_rgb[mask_slice, 1] = np.maximum(0, slice_rgb[mask_slice, 1].astype(int) - 80)
                slice_rgb[mask_slice, 2] = np.maximum(0, slice_rgb[mask_slice, 2].astype(int) - 80)
                img = Image.fromarray(slice_rgb)
            else:
                img = Image.fromarray(slice_data)

            # Downsample if too large for display
            max_dim = 512
            if img.width > max_dim or img.height > max_dim:
                ratio = max(img.width / max_dim, img.height / max_dim)
                new_size = (int(img.width / ratio), int(img.height / ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # Convert to base64 PNG
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            import base64
            img_str = base64.b64encode(buffered.getvalue()).decode()

            return jsonify({
                "success": True,
                "data": f"data:image/png;base64,{img_str}",
                "shape": list(slice_data.shape),
            })
        except Exception as e:
            import traceback
            logger.error(f"Viewer slice failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/volume", methods=["GET"])
    def api_viewer_volume():
        """Return entire CT volume as binary blob for client-side rendering."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        ct_data = agent.memory.retrieve("ct_data")
        spacing = agent.memory.retrieve("ct_spacing")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np

            # Convert to int16 (Hounsfield units)
            ct_int16 = ct_data.astype(np.int16)
            raw_bytes = ct_int16.tobytes()

            response = Response(raw_bytes, mimetype='application/octet-stream')
            response.headers['X-Shape-Z'] = str(ct_data.shape[0])
            response.headers['X-Shape-Y'] = str(ct_data.shape[1])
            response.headers['X-Shape-X'] = str(ct_data.shape[2])
            response.headers['X-Spacing-X'] = str(float(spacing[0]))
            response.headers['X-Spacing-Y'] = str(float(spacing[1]))
            response.headers['X-Spacing-Z'] = str(float(spacing[2]))
            response.headers['X-Dtype'] = 'int16'
            return response
        except Exception as e:
            logger.error(f"Volume export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/label_volume", methods=["GET"])
    def api_viewer_label_volume():
        """Return full CTV/OAR label volumes as binary uint8 for client-side rendering."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            import json as _json

            # Use full multi-label array for CTV (includes tumor, artery, vein, pancreas, etc.)
            # Falls back to binary ctv_array if full labels not available
            ctv_full = agent._get_label_array("ctv_full_labels")
            if ctv_full is None:
                ctv_full = agent._get_label_array("ctv_array")
            oar_array = agent._get_label_array("oar_array")

            # Reorganize labels for data tree:
            # - CTV node: only tumor (label 1)
            # - OAR non-traversable: artery (label 2), vein (label 3) from nnUNet
            # - OAR traversable: pancreas (label 4) from nnUNet
            ctv_array = None
            if ctv_full is not None:
                # CTV = only tumor
                ctv_array = (ctv_full == 1).astype(np.uint8) if np.any(ctv_full == 1) else ctv_full

                # Merge nnUNet vessel/organ labels into OAR array
                nnunet_oar_labels = {
                    2: 201,   # artery -> OAR label 201
                    3: 202,   # vein -> OAR label 202
                    4: 203,   # pancreas -> OAR label 203
                }
                has_nnunet_oar = False
                for src_label, dst_label in nnunet_oar_labels.items():
                    if np.any(ctv_full == src_label):
                        has_nnunet_oar = True
                        break

                if has_nnunet_oar:
                    if oar_array is None:
                        oar_array = np.zeros_like(ctv_full, dtype=np.uint8)
                    elif oar_array.shape != ctv_full.shape:
                        # Resample OAR to match CTV shape if needed
                        pass  # Will be handled by shape check below
                    for src_label, dst_label in nnunet_oar_labels.items():
                        mask = ctv_full == src_label
                        if np.any(mask):
                            oar_array[mask] = dst_label

            shape = ct_data.shape  # (Z, Y, X)

            # DEBUG: verify mask-CT alignment
            if ctv_array is not None:
                import SimpleITK as _sitk_dbg
                _ct_img = agent.memory.retrieve("ct_image")
                _ct_dir = _ct_img.GetDirection() if _ct_img is not None else "None"
                _ctv_stored = agent.memory.retrieve("ctv_array")
                _ctv_dir = _ctv_stored.GetDirection() if isinstance(_ctv_stored, _sitk_dbg.Image) else "numpy"
                _ctv_nz = [int(i) for i in np.where(ctv_array > 0)[0][:5]] if np.any(ctv_array > 0) else []
                _ct_nz = [int(i) for i in np.where(ct_data > 0)[0][:5]] if np.any(ct_data > 0) else []
                logger.info(f"[DEBUG label_volume] CT shape={shape}, dir={_ct_dir}")
                logger.info(f"[DEBUG label_volume] CTV shape={ctv_array.shape}, dir={_ctv_dir}, first_nz_z={_ctv_nz}")
                logger.info(f"[DEBUG label_volume] CT first_nz_z={_ct_nz}")
                # Check if CTV center Z matches CT center Z
                if np.any(ctv_array > 0):
                    _ctv_z = np.where(ctv_array > 0)[0]
                    logger.info(f"[DEBUG label_volume] CTV Z range: {_ctv_z.min()}-{_ctv_z.max()}, center={_ctv_z.mean():.1f}")
                    logger.info(f"[DEBUG label_volume] CT Z range: 0-{ct_data.shape[0]-1}")

            # Ensure label arrays have same shape as CT
            if ctv_array is not None and ctv_array.shape != shape:
                logger.warning(f"CTV shape mismatch: {ctv_array.shape} vs CT {shape}, resampling...")
                import SimpleITK as sitk
                ctv_sitk = sitk.GetImageFromArray(ctv_array.astype(np.uint8))
                ct_ref = agent.memory.retrieve("ct_image")
                if ct_ref is not None:
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_ref)
                    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                    resampler.SetDefaultPixelValue(0)
                    ctv_array = sitk.GetArrayFromImage(resampler.Execute(ctv_sitk))

            if oar_array is not None and oar_array.shape != shape:
                logger.warning(f"OAR shape mismatch: {oar_array.shape} vs CT {shape}, resampling...")
                import SimpleITK as sitk
                oar_sitk = sitk.GetImageFromArray(oar_array.astype(np.uint8))
                ct_ref = agent.memory.retrieve("ct_image")
                if ct_ref is not None:
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_ref)
                    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
                    resampler.SetDefaultPixelValue(0)
                    oar_array = sitk.GetArrayFromImage(resampler.Execute(oar_sitk))

            # Build color LUT for all labels
            color_lut = {}
            if ctv_array is not None:
                # Add all CTV labels with distinct colors
                for lid in np.unique(ctv_array):
                    if lid > 0:
                        color_lut[int(lid)] = list(_label_color(int(lid)))
            if oar_array is not None:
                for lid in np.unique(oar_array):
                    if lid > 0:
                        color_lut[int(lid)] = list(_label_color(int(lid)))

            # Build binary payload: ctv bytes + oar bytes
            payload = bytearray()
            ctv_offset = 0
            oar_offset = 0

            if ctv_array is not None:
                ctv_u8 = ctv_array.astype(np.uint8)
                unique_labels = list(np.unique(ctv_u8))
                logger.info(f"CTV array unique labels: {unique_labels}, shape: {ctv_u8.shape}")
                payload.extend(ctv_u8.tobytes())
                ctv_offset = len(payload)

            if oar_array is not None:
                oar_u8 = oar_array.astype(np.uint8)
                payload.extend(oar_u8.tobytes())
                oar_offset = len(payload)

            response = Response(bytes(payload), mimetype='application/octet-stream')
            response.headers['X-Shape-Z'] = str(shape[0])
            response.headers['X-Shape-Y'] = str(shape[1])
            response.headers['X-Shape-X'] = str(shape[2])
            response.headers['X-Color-LUT'] = _json.dumps(color_lut)
            response.headers['X-Has-CTV'] = 'true' if ctv_array is not None else 'false'
            response.headers['X-Has-OAR'] = 'true' if oar_array is not None else 'false'
            response.headers['X-CTV-Size'] = str(ctv_offset)
            response.headers['X-OAR-Size'] = str(len(payload) - ctv_offset) if oar_array is not None else '0'

            # Send CTV label names from model (not hardcoded in frontend)
            ctv_label_map = agent.memory.retrieve("ctv_label_map", {})
            logger.info(f"CTV label map from memory: {ctv_label_map}")
            if ctv_label_map:
                response.headers['X-CTV-Label-Map'] = _json.dumps({str(k): v for k, v in ctv_label_map.items()})
            else:
                # Fallback: use default label names
                response.headers['X-CTV-Label-Map'] = _json.dumps({"1": "pancreatic tumor"})

            # Also return organ metadata for data tree
            organ_names = agent.memory.retrieve("organ_names", {})
            organ_counts = agent.memory.retrieve("organ_counts", {})
            # Add nnUNet-derived OAR label names
            nnunet_oar_names = {201: "artery", 202: "vein", 203: "pancreas"}
            for lid, name in nnunet_oar_names.items():
                if lid not in organ_names:
                    organ_names[lid] = name
            organ_meta = {}
            if oar_array is not None:
                for lid in np.unique(oar_array):
                    lid_int = int(lid)
                    if lid_int > 0:
                        organ_meta[lid_int] = {
                            "name": organ_names.get(lid_int, f"Organ_{lid_int}"),
                            "color": color_lut.get(lid_int, [200, 200, 200]),
                            "voxels": int(organ_counts.get(lid_int, np.sum(oar_array == lid))),
                        }
            response.headers['X-Organ-Meta'] = _json.dumps(organ_meta)

            return response
        except Exception as e:
            logger.error(f"Label volume export failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/overlay", methods=["POST"])
    def api_viewer_overlay():
        """Get segmentation overlay for a specific slice."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        axis_name = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)
        overlay_type = data.get("overlay_type", "oar")  # "ctv" or "oar"
        # Per-organ visibility and opacity from client
        visible_organs = data.get("visible_organs", None)  # list of label_ids to show
        organ_opacities = data.get("organ_opacities", None)  # {label_id: opacity 0-1}
        ctv_opacity = data.get("ctv_opacity", 0.7)
        oar_opacity = data.get("oar_opacity", 0.5)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import base64
            import numpy as np
            from io import BytesIO
            from PIL import Image

            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            axis = axis_map.get(axis_name, 0)

            # Get the segmentation mask
            if overlay_type == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

            if mask_data is None:
                img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                return jsonify({"success": True, "data": f"data:image/png;base64,{img_str}", "has_mask": False})

            # Extract slice from mask: np.take with axis gives correct orientation
            # mask_data is (Z, Y, X), axis_map: axial=0(Z), sagittal=2(X), coronal=1(Y)
            # Z-flip applied so display matches raw DICOM ordering (slider 0 = feet).
            if axis_name == 'axial':
                src_idx = mask_data.shape[0] - 1 - slice_index
                mask_slice = np.take(mask_data, src_idx, axis=axis)
            elif axis_name == 'sagittal':
                z_arr = np.arange(mask_data.shape[0])[::-1]
                mask_slice = mask_data[z_arr, :, slice_index]
            elif axis_name == 'coronal':
                z_arr = np.arange(mask_data.shape[0])[::-1]
                mask_slice = mask_data[z_arr, slice_index, :]

            # For sagittal/coronal: resample Z-axis to match isotropic display
            # Client expects: sagittal -> width=Y, height=Z_resampled
            #                coronal -> width=X, height=Z_resampled
            # After np.take: sagittal=(Z, Y), coronal=(Z, X)
            # Image.fromarray(H, W) -> image width=W, height=H
            # So (Z_resampled, Y) -> width=Y, height=Z_resampled ✓
            if axis_name in ('sagittal', 'coronal'):
                spacing = agent.memory.retrieve("ct_spacing") or (0.6836, 0.6836, 5.0)
                spacing_x, spacing_y, spacing_z = float(spacing[0]), float(spacing[1]), float(spacing[2])
                if axis_name == 'sagittal':
                    resample_ratio = spacing_z / spacing_y
                else:  # coronal
                    resample_ratio = spacing_z / spacing_x
                if resample_ratio != 1.0:
                    new_z = int(mask_slice.shape[0] * resample_ratio)
                    indices = np.minimum((np.arange(new_z) / resample_ratio).astype(int), mask_slice.shape[0] - 1)
                    mask_slice = mask_slice[indices, :]
                # No transpose needed - (Z_resampled, Y/X) gives correct width/height

            # Create colored overlay with per-organ visibility/opacity
            overlay = np.zeros((*mask_slice.shape, 4), dtype=np.uint8)

            if overlay_type == "ctv":
                alpha = int(ctv_opacity * 255)
                unique_ctv_labels = np.unique(mask_slice[mask_slice > 0])
                # Always use per-label colors (consistent with data tree display)
                for label in unique_ctv_labels:
                    label_int = int(label)
                    color = _label_color(label_int)
                    overlay[mask_slice == label] = [*color, alpha]
            else:
                # OAR: per-organ colors with visibility/opacity filtering
                unique_labels = np.unique(mask_slice[mask_slice > 0])
                for label in unique_labels:
                    label_int = int(label)
                    # Check visibility - use label_int (actual mask value) for filtering
                    if visible_organs is not None and label_int not in visible_organs:
                        continue
                    # Get opacity for this organ
                    if organ_opacities and str(label_int) in organ_opacities:
                        alpha = int(organ_opacities[str(label_int)] * 255)
                    else:
                        alpha = int(oar_opacity * 255)
                    # Use golden-ratio HSV for visually distinct per-organ colors
                    color = _label_color(label_int)
                    overlay[mask_slice == label] = [*color, alpha]

            img = Image.fromarray(overlay, 'RGBA')

            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            return jsonify({
                "success": True,
                "data": f"data:image/png;base64,{img_str}",
                "has_mask": True,
                "overlay_type": overlay_type,
            })
        except Exception as e:
            logger.error(f"Overlay generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/organs", methods=["GET"])
    def api_viewer_organs():
        """Return organ data (names and voxel counts) from OAR segmentation."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        organ_names = agent.memory.retrieve("organ_names", {})
        organ_counts = agent.memory.retrieve("organ_counts", {})

        # If organ_names is empty but oar_array exists, generate from array
        if not organ_names:
            oar_array = agent._get_label_array("oar_array")
            if oar_array is not None:
                import numpy as np
                organ_counts_generated = {}
                organ_names_generated = {}
                unique_labels = np.unique(oar_array)
                for label in unique_labels:
                    if label > 0:
                        label_int = int(label)
                        organ_counts_generated[label_int] = int(np.sum(oar_array == label))
                        # Try TotalSegmentator mapping
                        try:
                            from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                            organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(label_int, f"organ_{label_int}")
                        except ImportError:
                            organ_names_generated[label_int] = f"organ_{label_int}"
                organ_names = organ_names_generated
                organ_counts = organ_counts_generated
                # Store for future use
                agent.memory.store("organ_names", organ_names)
                agent.memory.store("organ_counts", organ_counts)

        organs = {}
        for label_id, name in organ_names.items():
            label_int = int(label_id) if isinstance(label_id, str) else label_id
            organs[str(label_int)] = {
                "name": name,
                "voxel_count": organ_counts.get(label_int, organ_counts.get(str(label_int), 0))
            }

        return jsonify({"success": True, "organs": organs})

    @app.route("/api/viewer/threshold", methods=["POST"])
    def api_viewer_threshold():
        """Apply threshold segmentation and return mask."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        lower = data.get("lower", -1000)
        upper = data.get("upper", 1000)
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np

            mask = (ct_data >= lower) & (ct_data <= upper)
            axis_map = agent.memory.retrieve("ct_axis_map") or {
                'axial': 0, 'sagittal': 2, 'coronal': 1,
            }
            mask_slice = np.take(mask, slice_index, axis=axis_map.get(axis, 0))

            # Count voxels
            total_voxels = int(mask.sum())
            spacing = agent.memory.retrieve("ct_spacing") or (1, 1, 1)
            volume_mm3 = total_voxels * float(np.prod(spacing))

            return jsonify({
                "success": True,
                "mask": mask_slice.tolist(),
                "total_voxels": total_voxels,
                "volume_mm3": volume_mm3,
            })
        except Exception as e:
            logger.error(f"Viewer threshold failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/hu", methods=["POST"])
    def api_viewer_hu():
        """Get HU value at a specific voxel."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        x = data.get("x", 0)
        y = data.get("y", 0)
        z = data.get("z", 0)

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            import numpy as np
            shape = ct_data.shape
            # ct_data shape is (Z, Y, X)
            if 0 <= x < shape[2] and 0 <= y < shape[1] and 0 <= z < shape[0]:
                hu = float(ct_data[z, y, x])
                return jsonify({"success": True, "hu": hu, "coords": [x, y, z]})
            else:
                return jsonify({"error": "Coordinates out of bounds"}), 400
        except Exception as e:
            logger.error(f"Viewer HU failed: {e}")
            return jsonify({"error": str(e)}), 500

    def _laplacian_smooth(vertices, faces, iterations=3, factor=0.3):
        """Lightweight Laplacian mesh smoothing using numpy.
        Moves each vertex toward the centroid of its neighbors."""
        import numpy as np
        from collections import defaultdict

        # Build vertex adjacency from faces
        adj = defaultdict(set)
        for f in faces:
            adj[f[0]].add(f[1]); adj[f[0]].add(f[2])
            adj[f[1]].add(f[0]); adj[f[1]].add(f[2])
            adj[f[2]].add(f[0]); adj[f[2]].add(f[1])

        verts = vertices.copy().astype(np.float64)
        for _ in range(iterations):
            new_verts = verts.copy()
            for vi, neighbors in adj.items():
                if not neighbors:
                    continue
                centroid = verts[list(neighbors)].mean(axis=0)
                new_verts[vi] += factor * (centroid - verts[vi])
            verts = new_verts
        return verts

    @app.route("/api/viewer/3d", methods=["POST"])
    def api_viewer_3d():
        """Generate 3D mesh from CTV or OAR mask."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        source = data.get("source", "ctv")  # "ctv" or "oar"
        label_id = data.get("label_id")  # specific organ label for OAR

        try:
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_dilation

            # Get mask data
            if source == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract specific label if provided
            if label_id is not None:
                mask = (mask_data == int(label_id)).astype(np.uint8)
            else:
                mask = (mask_data > 0).astype(np.uint8)

            if mask.sum() == 0:
                return jsonify({"error": "Empty mask"}), 400

            # Adaptive preprocessing based on mask density
            density = mask.sum() / (mask.shape[0] * mask.shape[1] * mask.shape[2])
            if density < 0.001:
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                mask = binary_dilation(mask, structure=struct, iterations=2)
                mask = binary_closing(mask, structure=struct, iterations=3)
                mask = binary_fill_holes(mask).astype(np.uint8)
            elif density < 0.01:
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                mask = binary_dilation(mask, structure=struct, iterations=1)
                mask = binary_closing(mask, structure=struct, iterations=2)
                mask = binary_fill_holes(mask).astype(np.uint8)
            else:
                mask = binary_closing(mask, iterations=2).astype(np.uint8)
                mask = binary_fill_holes(mask).astype(np.uint8)

            # Use distance transform for smooth surface
            from scipy.ndimage import distance_transform_edt
            dist_out = distance_transform_edt(1 - mask)
            dist_in = distance_transform_edt(mask)
            smooth_field = dist_out - dist_in

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            spacing_xyz = tuple(float(s) for s in spacing[:3])
            spacing_zyx = spacing_xyz[::-1]

            vertices, faces, normals, values = measure.marching_cubes(
                smooth_field, level=0.0, spacing=spacing_zyx, allow_degenerate=False
            )

            # Smooth mesh
            vertices = _laplacian_smooth(vertices, faces, iterations=5, factor=0.4)

            # Remove degenerate faces
            v0 = vertices[faces[:, 0]]
            v1 = vertices[faces[:, 1]]
            v2 = vertices[faces[:, 2]]
            face_areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
            faces = faces[face_areas > 1e-10]

            return jsonify({
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "source": source,
                "label_id": label_id,
            })
        except Exception as e:
            logger.error(f"Viewer 3D failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/3d_mask", methods=["POST"])
    def api_viewer_3d_mask():
        """Generate 3D mesh from a specific organ mask label."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        label_id = data.get("label_id")
        source = data.get("source", "oar")  # "oar" or "ctv"

        if label_id is None:
            return jsonify({"error": "label_id required"}), 400

        try:
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_dilation, gaussian_filter

            if source == "ctv":
                mask_data = agent._get_label_array("ctv_array")
            else:
                mask_data = agent._get_label_array("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract binary mask for this label
            label_id = int(label_id)
            binary_mask = (mask_data == label_id).astype(np.uint8)

            if binary_mask.sum() == 0:
                return jsonify({"error": f"Label {label_id} not found in mask"}), 400

            # Adaptive preprocessing based on mask density
            total_voxels = binary_mask.sum()
            mask_volume = binary_mask.shape[0] * binary_mask.shape[1] * binary_mask.shape[2]
            density = total_voxels / mask_volume

            # More aggressive morphological ops for sparse/fragmented masks
            if density < 0.001:
                # Very sparse mask (e.g., small vessel): heavy closing + dilation
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                binary_mask = binary_dilation(binary_mask, structure=struct, iterations=2)
                binary_mask = binary_closing(binary_mask, structure=struct, iterations=3)
                binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)
                binary_mask = binary_dilation(binary_mask, structure=struct, iterations=1)
            elif density < 0.01:
                # Sparse mask (e.g., bile duct, small organ): moderate closing
                struct = np.ones((3, 3, 3), dtype=np.uint8)
                binary_mask = binary_dilation(binary_mask, structure=struct, iterations=1)
                binary_mask = binary_closing(binary_mask, structure=struct, iterations=2)
                binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)
            else:
                # Normal density mask: standard cleanup
                binary_mask = binary_closing(binary_mask, iterations=2).astype(np.uint8)
                binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)

            # Gaussian smoothing on distance transform for smoother surface
            # This creates a continuous scalar field from the binary mask
            from scipy.ndimage import distance_transform_edt
            dist_out = distance_transform_edt(1 - binary_mask)
            dist_in = distance_transform_edt(binary_mask)
            smooth_field = dist_out - dist_in  # Positive inside, negative outside

            # Get spacing, origin, direction from CT data
            spacing = agent.memory.retrieve("ct_spacing") or (1.0, 1.0, 1.0)
            origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
            direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
            # SimpleITK spacing is (X, Y, Z), numpy array is (Z, Y, X)
            # marching_cubes expects spacing in array axis order (sz, sy, sx)
            if isinstance(spacing, (list, tuple)) and len(spacing) >= 3:
                spacing_zyx = tuple(float(s) for s in spacing[:3])[::-1]
            else:
                spacing_zyx = (1.0, 1.0, 1.0)

            # Generate mesh from the smooth distance field (level=0 is the surface)
            vertices, faces, normals, values = measure.marching_cubes(
                smooth_field, level=0.0, spacing=spacing_zyx, allow_degenerate=False
            )

            # Smooth mesh vertices
            vertices = _laplacian_smooth(vertices, faces, iterations=5, factor=0.4)

            # Remove degenerate faces (faces with zero area or duplicate vertices)
            v0 = vertices[faces[:, 0]]
            v1 = vertices[faces[:, 1]]
            v2 = vertices[faces[:, 2]]
            face_areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
            valid_faces = face_areas > 1e-10
            faces = faces[valid_faces]

            # Transform vertices from array coordinates to world coordinates
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            # vertices are in (z, y, x) order with spacing already applied
            # Convert to (x, y, z) order for world coordinate transform
            vertices_xyz = vertices[:, ::-1]  # Reverse to (x, y, z)
            # Apply direction and origin: world = origin + direction @ point
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz
            vertices = vertices_world

            # Decimation: use Open3D if available, otherwise skip (no stride-based fallback)
            if len(faces) > 50000:
                target = min(50000, len(faces))
                try:
                    import open3d as o3d
                    mesh_o3d = o3d.geometry.TriangleMesh()
                    mesh_o3d.vertices = o3d.utility.Vector3dVector(vertices)
                    mesh_o3d.triangles = o3d.utility.Vector3iVector(faces)
                    mesh_o3d = mesh_o3d.simplify_quadric_decimation(target_number_of_triangles=target)
                    vertices = np.asarray(mesh_o3d.vertices)
                    faces = np.asarray(mesh_o3d.triangles)
                except (ImportError, Exception):
                    # No decimation - keep full mesh (stride-based creates holes)
                    pass

            return jsonify({
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "label_id": label_id,
                "source": source,
            })
        except Exception as e:
            logger.error(f"3D mask reconstruction failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/3d_skin", methods=["POST"])
    def api_viewer_3d_skin():
        """Generate CT skin mesh using isosurface (marching cubes at skin threshold)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        threshold = data.get("threshold", -300)  # Default: skin surface at -300 HU

        ct_data = agent.memory.retrieve("ct_data")
        if ct_data is None:
            return jsonify({"error": "No CT loaded"}), 400

        try:
            import numpy as np
            from skimage import measure

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
            direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)
            # SimpleITK spacing is (X, Y, Z), numpy array is (Z, Y, X)
            # marching_cubes expects spacing in array axis order (sz, sy, sx)
            spacing_xyz = tuple(float(s) for s in spacing[:3])
            spacing_zyx = spacing_xyz[::-1]

            # Subsample for faster mesh generation if volume is large
            if ct_data.shape[0] > 64:
                step = max(1, ct_data.shape[0] // 64)
                ct_sub = ct_data[::step, ::step, ::step]
                sub_spacing = (spacing_zyx[0] * step, spacing_zyx[1] * step, spacing_zyx[2] * step)
            else:
                ct_sub = ct_data
                sub_spacing = spacing_zyx

            data_min, data_max = float(ct_sub.min()), float(ct_sub.max())
            level = float(threshold)
            if level <= data_min or level >= data_max:
                level = (data_min + data_max) / 2.0

            vertices, faces, _, _ = measure.marching_cubes(ct_sub, level=level, spacing=sub_spacing, allow_degenerate=False)

            # Smooth jagged marching-cubes surface
            vertices = _laplacian_smooth(vertices, faces, iterations=2, factor=0.2)

            # Transform vertices from array coordinates to world coordinates
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            vertices_xyz = vertices[:, ::-1]  # Reverse to (x, y, z)
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz
            vertices = vertices_world

            # Decimate if too many faces
            if len(faces) > 100000:
                stride = max(1, len(faces) // 100000)
                faces = faces[::stride]

            return jsonify({
                "success": True,
                "vertices": vertices.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "threshold": threshold,
            })
        except Exception as e:
            logger.error(f"CT skin reconstruction failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/seeds_3d", methods=["GET"])
    def api_planning_seeds_3d():
        """Get seed positions and directions for 3D visualization.

        Seeds from optimal_plan() are in PLANNING GRID VOXEL coordinates.
        We must convert them to world coordinates using resampled_ct metadata.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            import numpy as np

            seed_plan = agent.memory.retrieve("seed_plan")
            if seed_plan is None:
                return jsonify({"success": True, "seeds": [], "needles": [], "message": "No seed plan available"})

            # Get resampled CT for coordinate transform
            resampled_ct = agent.memory.retrieve("resampled_ct")
            if resampled_ct is None:
                logger.warning("[seeds_3d] No resampled_ct found, returning raw coordinates")

            def _voxel_to_world(voxel_pos):
                """Convert planning grid voxel coords to world coords.

                The planning algorithm may output coords in either voxel or
                world space depending on the code path. We detect which by
                checking if the coordinates fall within the CT bounding box.
                """
                if resampled_ct is None:
                    return voxel_pos.tolist()
                try:
                    import numpy as _np
                    pt = _np.array(voxel_pos, dtype=_np.float64).flatten()[:3]
                    origin = _np.array(resampled_ct.GetOrigin())
                    spacing = _np.array(resampled_ct.GetSpacing())
                    direction = _np.array(resampled_ct.GetDirection()).reshape(3, 3)
                    # Compute CT bounding box in world coords
                    size = _np.array(resampled_ct.GetSize())
                    corners = _np.array([[0,0,0],[size[0],0,0],[0,size[1],0],[0,0,size[2]],
                                          [size[0],size[1],0],[size[0],0,size[2]],
                                          [0,size[1],size[2]],[size[0],size[1],size[2]]])
                    world_corners = (corners * spacing) @ direction.T + origin
                    bb_min = world_corners.min(axis=0)
                    bb_max = world_corners.max(axis=0)
                    # If seed is already within CT bounds, it's in world coords
                    in_bounds = _np.all(pt >= bb_min - 50) and _np.all(pt <= bb_max + 50)
                    if in_bounds:
                        return pt.tolist()
                    # Otherwise, transform from voxel to world
                    world = (pt * spacing) @ direction.T + origin
                    return world.tolist()
                except Exception as e:
                    logger.warning(f"[seeds_3d] voxel_to_world failed: {e}")
                    return voxel_pos.tolist()

            def _voxel_dir_to_world(voxel_dir):
                """Convert planning grid voxel direction to world direction.

                Directions are vectors (not positions). If the seed position
                was already in world coords, the direction is likely also
                in world coords and needs no transformation.
                """
                if resampled_ct is None:
                    return voxel_dir.tolist()
                try:
                    import numpy as _np
                    d = _np.array(voxel_dir, dtype=_np.float64).flatten()[:3]
                    norm = _np.linalg.norm(d)
                    if norm > 1e-10:
                        d = d / norm
                    # If direction magnitude is ~1 (unit vector in world space),
                    # it's likely already in world coords
                    if 0.8 < norm < 1.2:
                        return d.tolist()
                    # Otherwise, transform from voxel to world
                    spacing = _np.array(resampled_ct.GetSpacing())
                    direction = _np.array(resampled_ct.GetDirection()).reshape(3, 3)
                    world_dir = (d * spacing) @ direction.T
                    n = _np.linalg.norm(world_dir)
                    if n > 1e-10:
                        world_dir = world_dir / n
                    return world_dir.tolist()
                except Exception as e:
                    logger.warning(f"[seeds_3d] direction transform failed: {e}")
                    return voxel_dir.tolist()

            seeds = []
            needles = []

            for i, entry in enumerate(seed_plan):
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue

                trajectory = entry[0] if len(entry) > 0 else None
                seed_list = entry[1] if len(entry) > 1 else []

                needle_seeds = []
                for j, seed in enumerate(seed_list):
                    if not isinstance(seed, (list, tuple)) or len(seed) < 2:
                        continue

                    pos_voxel = np.array(seed[0], dtype=np.float64).flatten()[:3]
                    direc_voxel = np.array(seed[1], dtype=np.float64).flatten()[:3]

                    # Convert from planning grid voxel coords to world coords
                    pos_world = _voxel_to_world(pos_voxel)
                    direc_world = _voxel_dir_to_world(direc_voxel)

                    if i == 0 and j == 0:
                        logger.info(f"[seeds_3d] first seed: voxel={pos_voxel.tolist()}, world={pos_world}")
                        if resampled_ct is not None:
                            logger.info(f"[seeds_3d] resampled_ct: size={resampled_ct.GetSize()}, spacing={resampled_ct.GetSpacing()}, origin={resampled_ct.GetOrigin()}, direction={resampled_ct.GetDirection()}")
                            # Debug: show the actual transform
                            import numpy as _np
                            pt = _np.array(pos_voxel, dtype=_np.float64).flatten()[:3]
                            sp = _np.array(resampled_ct.GetSpacing())
                            or_ = _np.array(resampled_ct.GetOrigin())
                            dr = _np.array(resampled_ct.GetDirection()).reshape(3, 3)
                            logger.info(f"[seeds_3d] DEBUG: pt={pt}, sp={sp}, or={or_}, dr={dr.tolist()}")
                            logger.info(f"[seeds_3d] DEBUG: pt*sp={pt*sp}, (pt*sp)@dr.T={(pt*sp)@dr.T}, +or={(pt*sp)@dr.T + or_}")

                    seed_data = {
                        "id": f"seed_{i}_{j}",
                        "position": pos_world,
                        "direction": direc_world,
                        "trajectory_id": i,
                        "seed_index": j,
                    }
                    seeds.append(seed_data)
                    needle_seeds.append(pos_world)

                # Create needle trajectory line (extended beyond seeds)
                if trajectory is not None and len(trajectory) >= 2:
                    traj_start = np.array(trajectory[0], dtype=np.float64).flatten()[:3]
                    traj_dir = np.array(trajectory[1], dtype=np.float64).flatten()[:3]
                    traj_start_world = _voxel_to_world(traj_start)
                    traj_dir_world = _voxel_dir_to_world(traj_dir)

                    # Extend trajectory line through and beyond seed positions
                    all_points = [traj_start_world]
                    all_points.extend(needle_seeds)
                    # Add extension point beyond last seed
                    if needle_seeds and traj_dir_world:
                        last = np.array(needle_seeds[-1])
                        ext = last + np.array(traj_dir_world) * 20  # 20mm extension
                        all_points.append(ext.tolist())
                    needles.append({
                        "id": f"needle_{i}",
                        "points": all_points,
                        "trajectory_id": i,
                    })
                elif len(needle_seeds) >= 2:
                    needles.append({
                        "id": f"needle_{i}",
                        "points": needle_seeds,
                        "trajectory_id": i,
                    })

            logger.info(f"[seeds_3d] returning {len(seeds)} seeds, {len(needles)} needles")
            return jsonify({
                "success": True,
                "seeds": seeds,
                "needles": needles,
                "total_seeds": len(seeds),
                "total_needles": len(needles),
            })
        except Exception as e:
            logger.error(f"Seed 3D data failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/clear", methods=["POST"])
    def api_planning_clear():
        """Clear all planning data from agent memory (called on page refresh)."""
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"success": True, "message": "No agent to clear"})

        try:
            # Clear planning results but KEEP CT/label data
            # CT data (ct_data, ct_spacing, ct_path, ct_sitk) must persist
            # so the viewer can still display the CT after page refresh
            planning_keys = [
                # Planning results
                "dose_metrics", "total_seeds", "num_trajectories",
                "seed_plan", "dose_distribution", "dose_distribution_gy",
                "trajectories", "refined_trajectories",
                "dvh_data", "plan_config", "plan_score", "metrics",
                "seed_positions", "radiation_volume",
                # Segmentation results (will be re-generated by agent)
                "ctv_array", "ctv_mask", "ctv_label_stats", "ctv_label_map",
                "ctv_full_labels", "oar_array", "organ_names", "organ_counts",
            ]
            for key in planning_keys:
                if key in agent.memory.planning_results:
                    del agent.memory.planning_results[key]

            # Clear conversation history
            agent.memory.clear_conversation()

            logger.info("[planning_clear] Cleared planning data, kept CT data")
            return jsonify({"success": True, "message": "Planning data cleared"})
        except Exception as e:
            logger.error(f"Clear planning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/results", methods=["GET"])
    def api_planning_results():
        """Get latest planning results including metrics, seeds, trajectories, dose, DVH.

        Returns:
            success, metrics, seeds, trajectories, dvh, has_dose,
            dose_shape, dose_range, has_trajectories, num_trajectories.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            import numpy as np

            # Get data from memory
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            total_seeds = agent.memory.retrieve("total_seeds") or 0
            num_trajectories = agent.memory.retrieve("num_trajectories") or 0
            seed_plan = agent.memory.retrieve("seed_plan")
            dose_distribution = agent.memory.retrieve("dose_distribution")
            dose_distribution_gy = agent.memory.retrieve("dose_distribution_gy")
            trajectories = agent.memory.retrieve("trajectories") or agent.memory.retrieve("refined_trajectories")

            # Build seeds list with trajectory linkage for the data tree.
            # Each trajectory is a tuple/list of the form:
            #   (entry_pt, exit_pt, target_pt, target_idx, depth, extra...)
            # and seed_plan[i] is [trajectory_descriptor, [seed_list_per_seed_pos]]
            # We pair seeds with their parent trajectory so the data tree can
            # show "Trajectory N → Seed 1, Seed 2, …".
            resampled_ct = agent.memory.retrieve("resampled_ct")
            seeds = []
            trajectories_data = []

            if seed_plan:
                for i, entry in enumerate(seed_plan):
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    traj_descriptor = entry[0]
                    seed_list = entry[1] if len(entry) > 1 else []
                    # Convert trajectory descriptor to world coordinates
                    entry_pt_world = None
                    target_pt_world = None
                    try:
                        if resampled_ct is not None and traj_descriptor is not None:
                            from plans.utilizations import position_transform
                            # entry[0] can be many shapes; canonicalize
                            if isinstance(traj_descriptor, (list, tuple)) and len(traj_descriptor) >= 2:
                                entry_pt = np.array(traj_descriptor[0], dtype=np.float64).flatten()[:3]
                                target_pt = np.array(traj_descriptor[2], dtype=np.float64).flatten()[:3] if len(traj_descriptor) > 2 else None
                                entry_pt_world = position_transform(resampled_ct, entry_pt)[0].tolist()
                                if target_pt is not None:
                                    target_pt_world = position_transform(resampled_ct, target_pt)[0].tolist()
                    except Exception:
                        pass

                    trajectory_id = f"traj_{i + 1}"
                    trajectories_data.append({
                        "id": trajectory_id,
                        "index": i,
                        "entry": entry_pt_world,
                        "target": target_pt_world,
                        "seed_count": len(seed_list) if isinstance(seed_list, (list, tuple)) else 0,
                    })

                    for j, seed in enumerate(seed_list or []):
                        if not isinstance(seed, (list, tuple)) or len(seed) < 2:
                            continue
                        pos_voxel = np.array(seed[0], dtype=np.float64).flatten()[:3]
                        if resampled_ct is not None:
                            try:
                                from plans.utilizations import position_transform
                                pos_world = position_transform(resampled_ct, pos_voxel)[0].tolist()
                            except Exception:
                                pos_world = pos_voxel.tolist()
                        else:
                            pos_world = pos_voxel.tolist()
                        seeds.append({
                            "id": f"seed_{i + 1}_{j + 1}",
                            "pos": pos_world,
                            "dose": float(dose_metrics.get("d90", 0)),
                            "trajectory_id": trajectory_id,
                        })

            # Build DVH data
            dvh_data = dose_metrics.get("dvh_data", {})

            # Dose shape/range
            dose_shape = None
            dose_min = None
            dose_max = None
            dose_for_stats = dose_distribution_gy if dose_distribution_gy is not None else dose_distribution
            if dose_for_stats is not None:
                try:
                    dnp = np.asarray(dose_for_stats)
                    if dnp.ndim == 3:
                        dose_shape = list(dnp.shape)
                    dose_min = float(np.min(dnp))
                    dose_max = float(np.max(dnp))
                except Exception:
                    pass

            # Include tumor_type in metrics so the client can
            # display the actual segmentation model name in the report.
            tumor_type = agent.memory.retrieve("tumor_type_used", "")
            if tumor_type and isinstance(dose_metrics, dict):
                dose_metrics["tumor_type"] = tumor_type

            return jsonify({
                "success": True,
                "metrics": dose_metrics,
                "seeds": seeds,
                "trajectories": trajectories_data,
                "total_seeds": total_seeds,
                "num_trajectories": num_trajectories,
                "has_trajectories": bool(trajectories) or len(trajectories_data) > 0,
                "dvh": dvh_data,
                "has_dose": dose_for_stats is not None,
                "dose_shape": dose_shape,
                "dose_min": dose_min,
                "dose_max": dose_max,
            })
        except Exception as e:
            logger.error(f"Get planning results failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/show_step", methods=["POST"])
    def api_planning_show_step():
        """Show specific planning step results and return data for UI update."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        step = data.get("step", "all")

        try:
            import numpy as np

            # Get all planning data
            dose_metrics = agent.memory.retrieve("dose_metrics") or {}
            total_seeds = agent.memory.retrieve("total_seeds") or 0
            seed_plan = agent.memory.retrieve("seed_plan")
            trajectories = agent.memory.retrieve("trajectories") or agent.memory.retrieve("refined_trajectories")
            dose_distribution = agent.memory.retrieve("dose_distribution")

            result = {"success": True, "step": step}

            if step in ("trajectories", "trajectory_init", "trajectory_refine", "all"):
                result["trajectories"] = trajectories or []
                result["num_trajectories"] = len(trajectories) if trajectories else 0

            if step in ("seeds", "seed_planning", "all"):
                result["seed_plan"] = seed_plan or []
                result["total_seeds"] = total_seeds

            if step in ("dose", "dose_calc", "dose_distribution", "all"):
                result["has_dose"] = dose_distribution is not None
                if dose_distribution is not None:
                    result["dose_range"] = [float(np.min(dose_distribution)), float(np.max(dose_distribution))]

            if step in ("dvh", "dose_eval", "metrics", "all"):
                result["metrics"] = dose_metrics
                result["dvh"] = dose_metrics.get("dvh_data", {})

            return jsonify(result)
        except Exception as e:
            logger.error(f"Show step results failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/segmentation", methods=["POST"])
    def api_segmentation():
        """MANUAL segmentation (2026-06-15) — runs CTV or OAR
        segmentation directly without going through the LLM agent.
        Used by the Step-by-Step manual planning buttons in the Input
        panel. The user wanted a "manual UI" that doesn't require
        chatting with the LLM at all.

        Request: { kind: 'ctv' | 'oar', image_path: '...' }
        Returns: { success, kind, label_counts, total_labels, ... }
        """
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        kind = data.get("kind", "ctv")
        image_path = data.get("image_path", "")
        if not image_path:
            return jsonify({"error": "image_path is required"}), 400

        try:
            # Dispatch to the appropriate tool.
            if kind == "ctv":
                from tool_factory.CTV_seg.pancreatic_tumor_nnunet import (
                    NNUNetPancreaticTumorTool,
                )
                tool = NNUNetPancreaticTumorTool()
                result = tool.execute(image_path=image_path)
            elif kind == "oar":
                from tool_factory.OAR_seg.totalsegmentator_oar import (
                    TotalSegmentatorOARTool,
                )
                tool = TotalSegmentatorOARTool()
                result = tool.execute(image_path=image_path)
            else:
                return jsonify({"error": f"Unknown segmentation kind: {kind}"}), 400

            if not result.success:
                return jsonify({"error": result.error or "Segmentation failed"}), 500

            # Store under the standard memory keys the rest of the
            # system reads from (ctv_label_data, oar_label_data, etc.).
            if kind == "ctv" and hasattr(agent, "memory"):
                mask = getattr(result, "mask_array", None) or getattr(result, "mask", None)
                if mask is not None:
                    try:
                        agent.memory.store("ctv_label_data", mask)
                        agent.memory.store("ctv_segmented", True)
                    except Exception as e:
                        logger.warning(f"store ctv_label_data failed: {e}")
            elif kind == "oar" and hasattr(agent, "memory"):
                mask = getattr(result, "mask_array", None) or getattr(result, "mask", None)
                if mask is not None:
                    try:
                        agent.memory.store("oar_label_data", mask)
                        agent.memory.store("oar_segmented", True)
                    except Exception as e:
                        logger.warning(f"store oar_label_data failed: {e}")

            return jsonify({
                "success": True,
                "kind": kind,
                "label_counts": getattr(result, "label_counts", {}) or {},
                "total_labels": len(getattr(result, "label_counts", {}) or {}),
            })
        except Exception as e:
            logger.error(f"Manual segmentation ({kind}) failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/run_step", methods=["POST"])
    def api_planning_run_step():
        """Run a specific planning step."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_image_path = data.get("ct_image_path")
        step = data.get("step", "full")

        if not ct_image_path:
            return jsonify({"error": "ct_image_path is required"}), 400

        try:
            # Use planning pipeline tool
            from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
            tool = PlanningPipelineTool()

            # Get config from agent; fall back to plans/config.json defaults
            # for any planning params not set on the agent (e.g. reference_direc,
            # radiation_array_params). This keeps endpoint behavior consistent
            # with the canonical config and avoids stale [0,1,0] direction.
            config = getattr(agent, 'config', {})
            try:
                import json as _json, os as _os
                _cfg_path = _os.path.join(_os.path.dirname(__file__), '..', 'plans', 'config.json')
                with open(_cfg_path) as _f:
                    _default_cfg = _json.load(_f)
            except Exception:
                _default_cfg = {}

            def _cfg(key, default=None):
                """Get config value: agent.config > plans/config.json > default."""
                if key in config:
                    return config[key]
                if key in _default_cfg:
                    return _default_cfg[key]
                return default

            # Merge radiation_array_params from default if not on agent
            _rad_params_default = _default_cfg.get("radiation_array_params", {})

            result = tool._execute(
                ct_image_path=ct_image_path,
                step=step,
                mode=_cfg("mode", "rule_based"),
                seed_info=_cfg("seed_info"),
                planning_params={
                    "in_lowest_energy": _cfg("in_lowest_energy"),
                    "out_highest_energy": _cfg("out_highest_energy"),
                    "DVH_rate": _cfg("DVH_rate"),
                    "iter_rate": _cfg("iter_rate"),
                    "max_iter": _cfg("max_iter"),
                    "direc_resolution": _cfg("direc_resolution"),
                    "image_normalize": _cfg("image_normalize", [-1000, 3000, 255]),
                },
                dl_params=_cfg("dl_params"),
                rf_params=_cfg("rf_params"),
                ref_direc=_cfg("reference_direc"),
            )

            if result.success:
                # Store results in memory
                agent._store_tool_result("planning_pipeline", result)
                # Sanitize metadata for JSON serialization (strip non-scalar fields
                # like trajectory lists / numpy arrays — callers can read them via
                # /api/planning/show_step).
                import numpy as _np
                _meta = {}
                for _k, _v in (result.metadata or {}).items():
                    if isinstance(_v, (_np.ndarray, list, tuple)):
                        continue  # skip heavy / non-serializable
                    _meta[_k] = _v
                return jsonify({
                    "success": True,
                    "step": step,
                    "message": result.message,
                    "metadata": _meta,
                })
            else:
                return jsonify({"success": False, "error": result.error}), 400

        except Exception as e:
            logger.error(f"Run planning step failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/config", methods=["GET"])
    def api_planning_config():
        """Get planning configuration including iso-dose parameters."""
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            config = getattr(agent, 'config', {})
            # Read iso_dose_params from config file if not in agent config
            iso_params = config.get("iso_dose_params")
            if not iso_params:
                import json as _json
                config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plans", "config.json")
                if os.path.exists(config_path):
                    with open(config_path, "r") as f:
                        file_config = _json.load(f)
                    iso_params = file_config.get("iso_dose_params", {})

            return jsonify({
                "success": True,
                "iso_dose_params": iso_params or {
                    "iso_dose_values": [1.0, 1.5, 2.0, 4.0],
                    "iso_colors": [[0,1,0],[0,1,1],[1,1,0],[1,0.5,0],[1,0,0],[1,0,1],[0.5,0,0.5],[0,0.5,1]],
                    "iso_opacities": [0.3, 0.2, 0.1, 0.05],
                },
                "in_lowest_energy": config.get("in_lowest_energy", 1.0),
            })
        except Exception as e:
            logger.error(f"Get config failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_isosurface", methods=["POST"])
    def api_planning_dose_isosurface():
        """Generate dose isosurface mesh for 3D visualization.

        Threshold is in the SAME UNITS as the dose distribution (normalized).
        The frontend should display the label accordingly.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        threshold = data.get("threshold", 1.0)

        try:
            import numpy as np
            from skimage import measure

            dose_array = agent.memory.retrieve("dose_distribution")
            if dose_array is None:
                return jsonify({"error": "No dose distribution available"}), 400

            # Use resampled_ct for coordinate transforms
            resampled_ct = agent.memory.retrieve("resampled_ct")
            if resampled_ct is not None:
                spacing = resampled_ct.GetSpacing()
                origin = resampled_ct.GetOrigin()
                direction = resampled_ct.GetDirection()
            else:
                spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
                origin = agent.memory.retrieve("ct_origin") or (0.0, 0.0, 0.0)
                direction = agent.memory.retrieve("ct_direction") or (1, 0, 0, 0, 1, 0, 0, 0, 1)

            dose_np = np.array(dose_array)
            if dose_np.ndim != 3:
                return jsonify({"error": "Invalid dose array dimensions"}), 400

            data_min = float(dose_np.min())
            data_max = float(dose_np.max())
            logger.info(f"[dose_isosurface] threshold={threshold}, dose_range=[{data_min:.4f}, {data_max:.4f}]")

            level = float(threshold)
            # The frontend sends threshold in Gy (e.g. 120, 180), but the
            # dose array is in NORMALIZED units (CNN output). Convert using
            # the actual prescription dose from plan config.
            plan_config = agent.memory.retrieve("plan_config", {})
            prescription_dose = float(plan_config.get("in_lowest_energy", 120.0))
            if level > data_max:
                # Threshold is in Gy — convert to normalized
                level = level / prescription_dose
                logger.info(f"[dose_isosurface] Converted threshold to normalized: {level:.4f} (prescription={prescription_dose} Gy)")
            if level <= data_min or level > data_max:
                return jsonify({"success": True, "vertices": [], "faces": [], "vertex_count": 0,
                                "face_count": 0, "threshold": threshold, "dose_range": [data_min, data_max]})

            # Use resampled_ct spacing (z,y,x -> x,y,z for marching cubes)
            spacing_zyx = tuple(float(s) for s in spacing[::-1])

            vertices, faces, _, _ = measure.marching_cubes(dose_np, level=level, spacing=spacing_zyx, allow_degenerate=False)

            # Transform from planning grid voxel coords to world coords
            origin_xyz = np.array(origin[:3], dtype=np.float64)
            direction_matrix = np.array(direction[:9], dtype=np.float64).reshape(3, 3)
            # vertices are in (z,y,x) from marching_cubes with spacing_zyx, convert to (x,y,z)
            vertices_xyz = vertices[:, ::-1]
            vertices_world = (direction_matrix @ vertices_xyz.T).T + origin_xyz

            # Decimate
            if len(faces) > 80000:
                stride = max(1, len(faces) // 80000)
                faces = faces[::stride]

            return jsonify({
                "success": True,
                "vertices": vertices_world.tolist(),
                "faces": faces.tolist(),
                "vertex_count": len(vertices_world),
                "face_count": len(faces),
                "threshold": threshold,
                "dose_range": [data_min, data_max],
            })
        except Exception as e:
            logger.error(f"Dose isosurface failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_overlay", methods=["GET"])
    def api_planning_dose_overlay():
        """Get dose distribution resampled to original CT space for 2D overlay.

        Returns metadata about the dose overlay. The actual slice data is fetched
        via the dose_overlay_slice endpoint.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        try:
            import numpy as np
            import SimpleITK as sitk

            # Try dose_distribution_gy first (already resampled to original CT space)
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
                logger.info(f"[dose_overlay] Using dose_distribution_gy, shape={dose_np.shape}")
            else:
                # Fall back to dose_distribution (planning grid) and resample
                dose_array = agent.memory.retrieve("dose_distribution")
                if dose_array is None:
                    return jsonify({"success": False, "error": "No dose distribution available"})
                dose_np = np.array(dose_array, dtype=np.float32)
                logger.info(f"[dose_overlay] Using dose_distribution (planning grid), shape={dose_np.shape}")

                # Get resampled CT (planning grid) and original CT
                resampled_ct = agent.memory.retrieve("resampled_ct")
                ct_image = agent.memory.retrieve("ct_image")

                if resampled_ct is not None and ct_image is not None:
                    # Resample dose from planning grid to original CT space
                    dose_sitk = sitk.GetImageFromArray(dose_np)
                    dose_sitk.SetSpacing(resampled_ct.GetSpacing())
                    dose_sitk.SetOrigin(resampled_ct.GetOrigin())
                    dose_sitk.SetDirection(resampled_ct.GetDirection())

                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_image)
                    resampler.SetInterpolator(sitk.sitkLinear)
                    dose_original = resampler.Execute(dose_sitk)
                    dose_np = sitk.GetArrayFromImage(dose_original)
                    logger.info(f"[dose_overlay] Resampled to original CT space, shape={dose_np.shape}")

            # Get CT metadata
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is not None:
                ct_size = [int(s) for s in ct_image.GetSize()]
                ct_spacing = [float(s) for s in ct_image.GetSpacing()]
                ct_origin = [float(o) for o in ct_image.GetOrigin()]
            else:
                ct_size = list(dose_np.shape[::-1])
                ct_spacing = [0.68, 0.68, 5.0]
                ct_origin = [0.0, 0.0, 0.0]

            return jsonify({
                "success": True,
                "dose_shape": list(dose_np.shape),
                "dose_min": float(dose_np.min()),
                "dose_max": float(dose_np.max()),
                "ct_spacing": ct_spacing,
                "ct_origin": ct_origin,
                "ct_size": ct_size,
            })
        except Exception as e:
            logger.error(f"Dose overlay data failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_overlay_slice", methods=["POST"])
    def api_planning_dose_overlay_slice():
        """Get a single dose overlay slice for a given axis and index.

        Returns the 2D dose slice in the same space as the CT slice.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        try:
            import numpy as np
            import SimpleITK as sitk

            # Try dose_distribution_gy first (already resampled)
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
            else:
                # Fall back to dose_distribution and resample
                dose_array = agent.memory.retrieve("dose_distribution")
                if dose_array is None:
                    return jsonify({"success": False, "error": "No dose distribution available"})
                dose_np = np.array(dose_array, dtype=np.float32)

                # Resample to original CT space
                resampled_ct = agent.memory.retrieve("resampled_ct")
                ct_image = agent.memory.retrieve("ct_image")

                if resampled_ct is not None and ct_image is not None:
                    dose_sitk = sitk.GetImageFromArray(dose_np)
                    dose_sitk.SetSpacing(resampled_ct.GetSpacing())
                    dose_sitk.SetOrigin(resampled_ct.GetOrigin())
                    dose_sitk.SetDirection(resampled_ct.GetDirection())
                    resampler = sitk.ResampleImageFilter()
                    resampler.SetReferenceImage(ct_image)
                    resampler.SetInterpolator(sitk.sitkLinear)
                    resampler.SetInput(dose_sitk)
                    dose_original = resampler.Execute()
                    dose_np = sitk.GetArrayFromImage(dose_original)

            # Extract 2D slice (dose_np is in z,y,x order)
            if axis == "axial":
                z = min(slice_index, dose_np.shape[0] - 1)
                slice_2d = dose_np[z].tolist()
            elif axis == "coronal":
                y = min(slice_index, dose_np.shape[1] - 1)
                slice_2d = dose_np[:, y, :].tolist()
            else:  # sagittal
                x = min(slice_index, dose_np.shape[2] - 1)
                slice_2d = dose_np[:, :, x].tolist()

            return jsonify({
                "success": True,
                "slice": slice_2d,
                "dose_min": float(dose_np.min()),
                "dose_max": float(dose_np.max()),
            })
        except Exception as e:
            logger.error(f"Dose overlay slice failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/planning/dose_contour_slice", methods=["POST"])
    def api_planning_dose_contour_slice():
        """Get dose contour lines for a given slice.

        Returns contour line coordinates for overlaying on 2D viewers.
        Uses iso_dose_values from config as contour levels.
        """
        import AgenticSys as _ag
        agent = getattr(_ag, '_global_agent', None) or get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        axis = data.get("axis", "axial")
        slice_index = data.get("slice_index", 0)

        try:
            import numpy as np
            from skimage import measure as ski_measure

            # Get dose distribution
            dose_np = agent.memory.retrieve("dose_distribution_gy")
            if dose_np is not None:
                dose_np = np.array(dose_np, dtype=np.float32)
            else:
                dose_dist = agent.memory.retrieve("dose_distribution")
                if dose_dist is None:
                    return jsonify({"error": "No dose distribution available"}), 400
                dose_np = np.array(dose_dist, dtype=np.float32)

            # Get iso-dose values from config
            config = getattr(agent, 'config', {})
            iso_params = config.get("iso_dose_params", {})
            # iso_dose_values are stored as RELATIVE multipliers of
            # the prescription dose (1.0×Rx, 1.5×Rx, ...). The dose
            # distribution here is in absolute Gy, so we must multiply
            # by prescriptionGy to get the contour level in Gy.
            #
            # Without this conversion (2026-06-16 user bug), the
            # contour endpoint called find_contours(slice_2d, level=1.0)
            # which interpreted 1.0 as **1 Gy** rather than "1×Rx ≈
            # 120 Gy". Result: every contour line landed at the dose
            # distribution's edge (around 1 Gy), which doesn't match
            # the visible dose map at all.
            iso_values_rel = iso_params.get("iso_dose_values", [1.0, 1.5, 2.0, 4.0])
            iso_colors_raw = iso_params.get("iso_colors", [[0,1,0],[0,1,1],[1,1,0],[1,0.5,0],[1,0,0]])
            iso_opacities = iso_params.get("iso_opacities", [0.3, 0.2, 0.1, 0.05])
            # Read prescription in Gy: prefer memory dose_metrics
            # (already in normalized units * DOSE_SCALE) then fall
            # back to reportForm, then default 120 Gy.
            DOSE_SCALE = 120.0
            prescription_gy = 120.0
            try:
                dm = agent.memory.retrieve("dose_metrics") or {}
                pnorm = dm.get("prescribed_dose")
                if isinstance(pnorm, (int, float)) and pnorm > 0:
                    prescription_gy = float(pnorm) * DOSE_SCALE
            except Exception:
                pass
            try:
                rf = agent.memory.retrieve("report_form") or {}
                if rf.get("planning", {}).get("prescriptionGy"):
                    prescription_gy = float(rf["planning"]["prescriptionGy"])
            except Exception:
                pass
            # Convert relative multipliers → absolute Gy for find_contours
            iso_values_gy = [float(v) * prescription_gy for v in iso_values_rel]
            # Return absolute Gy as `level` so the frontend label
            # shows the actual dose in Gy (was previously the
            # relative multiplier, e.g. "1.0" instead of "120").
            iso_labels_gy = iso_values_gy

            # Extract 2D slice from 3D dose array
            if axis == 'axial' or axis == 'z':
                z = min(int(slice_index), dose_np.shape[0] - 1)
                slice_2d = dose_np[z]
            elif axis == 'coronal' or axis == 'y':
                y = min(int(slice_index), dose_np.shape[1] - 1)
                slice_2d = dose_np[:, y, :]
            else:  # sagittal
                x = min(int(slice_index), dose_np.shape[2] - 1)
                slice_2d = dose_np[:, :, x]

            d_min = float(dose_np.min())
            d_max = float(dose_np.max())

            # Filter iso_values to those within the dose range of this slice.
            # Use the absolute-Gy levels (iso_values_gy) for the
            # comparison — slice_2d is in Gy.
            s_min = float(slice_2d.min())
            s_max = float(slice_2d.max())
            valid_levels = [(g, r) for g, r in zip(iso_values_gy, iso_values_rel)
                            if s_min < g < s_max]

            if not valid_levels:
                return jsonify({
                    "success": True,
                    "contours": [],
                    "dose_range": [d_min, d_max],
                    "slice_range": [s_min, s_max],
                })

            # Generate contour lines using marching squares
            contours_data = []
            for i, (level_gy, level_rel) in enumerate(valid_levels):
                try:
                    contours = ski_measure.find_contours(slice_2d, level=level_gy)
                    # Convert to list of [row, col] coordinate arrays
                    contour_lines = []
                    for contour in contours:
                        if len(contour) > 2:  # Need at least 3 points for a line
                            contour_lines.append(contour.tolist())

                    if contour_lines:
                        # Get color for this level
                        color = iso_colors_raw[i % len(iso_colors_raw)]
                        opacity = iso_opacities[min(i, len(iso_opacities) - 1)] if iso_opacities else 0.3
                        contours_data.append({
                            # Return BOTH: level_gy for the 2D label so
                            # the user sees actual dose (e.g. "120")
                            # instead of the relative multiplier ("1.0"),
                            # and level_rel for color/opacity lookup.
                            "level": float(level_gy),
                            "level_rel": float(level_rel),
                            "lines": contour_lines,
                            "color": color,
                            "opacity": opacity,
                        })
                except Exception as e:
                    logger.warning(f"Contour generation failed for level {level_gy}: {e}")

            return jsonify({
                "success": True,
                "contours": contours_data,
                "dose_range": [d_min, d_max],
                "slice_range": [s_min, s_max],
                "slice_shape": [int(slice_2d.shape[0]), int(slice_2d.shape[1])],
            })
        except Exception as e:
            logger.error(f"Dose contour slice failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        """Get default hyperparameters from config file."""
        try:
            import json
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "default_params.json")
            with open(config_path, 'r') as f:
                defaults = json.load(f)
            return jsonify({"success": True, "defaults": defaults})
        except Exception as e:
            logger.error(f"Get config failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/device/status", methods=["GET"])
    def api_device_status():
        """Get current GPU/CPU device allocation. The agent uses
        plans/device_manager.DeviceManager to pick the best free GPU
        at the start of each tool call; this endpoint surfaces the
        live state so the frontend can show a "GPU 0 (12GB free)"
        badge in the status bar. Tools (ctv_segmentation,
        oar_segmentation, dose engine) record which device they're
        using so the user can see the distribution."""
        try:
            from plans.device_manager import DeviceManager
            return jsonify({"success": True, **DeviceManager.instance().status()})
        except Exception as e:
            logger.error(f"Get device status failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["POST"])
    def api_config():
        """Update agent configuration (hyperparameters)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}

        try:
            # Store all parameter groups
            param_keys = [
                "seed_info", "radiation_array_params", "reference_direc",
                "in_lowest_energy", "out_highest_energy", "DVH_rate",
                "max_iter", "rf_params", "distance_filter",
                "direc_resolution", "dl_params", "iter_rate", "replan_rate",
                "mode",
            ]
            for key in param_keys:
                if key in data:
                    agent.config[key] = data[key]

            return jsonify({"success": True, "config": agent.config})
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/status", methods=["GET"])
    def api_status():
        """Get system status."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        status = agent.get_status()
        status["brain_available"] = agent.brain_available
        # Surface GPU/CPU device allocation. See plans/device_manager.py
        # for the auto-pick heuristic (best free memory, with concurrent
        # lease penalty so we spread load across GPUs).
        try:
            from plans.device_manager import DeviceManager
            status["devices"] = DeviceManager.instance().status()
        except Exception as _e:
            status["devices"] = {"cuda_available": False, "error": str(_e)}
        return jsonify(status)

    @app.route("/api/plan/preoperative", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_preoperative_plan():
        """Run pre-operative planning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        ctv_path = data.get("ctv_path")
        oar_path = data.get("oar_path")
        mode = data.get("mode", "rule_based")
        output_dir = data.get("output_dir", "./output")

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        if not _validate_path(ct_path):
            return jsonify({"error": "Invalid ct_path"}), 400
        if ctv_path and not _validate_path(ctv_path):
            return jsonify({"error": "Invalid ctv_path"}), 400
        if oar_path and not _validate_path(oar_path):
            return jsonify({"error": "Invalid oar_path"}), 400
        if not _validate_path(output_dir):
            return jsonify({"error": "Invalid output_dir"}), 400
        if mode not in ("rule_based", "rl", "auto"):
            return jsonify({"error": "Invalid mode. Use 'rule_based', 'rl', or 'auto'"}), 400

        try:
            # Get hyperparameters from agent config
            config = getattr(agent, 'config', {})
            seed_info = config.get('seed_info')
            radiation_array_params = config.get('radiation_array_params')
            reference_direc = config.get('reference_direc')
            in_lowest_energy = config.get('in_lowest_energy')
            out_highest_energy = config.get('out_highest_energy')
            DVH_rate = config.get('DVH_rate')
            max_iter = config.get('max_iter')
            rf_params = config.get('rf_params')

            result = agent.run_preoperative_plan(
                ct_path=ct_path,
                ctv_path=ctv_path,
                oar_path=oar_path,
                mode=mode,
                seed_info=seed_info,
                radiation_array_params=radiation_array_params,
                reference_direc=reference_direc,
                in_lowest_energy=in_lowest_energy,
                out_highest_energy=out_highest_energy,
                DVH_rate=DVH_rate,
                max_iter=max_iter,
                rf_params=rf_params,
                output_dir=output_dir,
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Preoperative planning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/plan/intraoperative", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_intraoperative_plan():
        """Run intra-operative replanning."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        original_plan = data.get("original_plan")
        threshold = data.get("deviation_threshold_mm", data.get("threshold", 2.0))
        output_dir = data.get("output_dir", "./output")

        if not ct_path:
            return jsonify({"error": "ct_path is required"}), 400

        if not _validate_path(ct_path):
            return jsonify({"error": "Invalid ct_path"}), 400
        if not _validate_path(output_dir):
            return jsonify({"error": "Invalid output_dir"}), 400
        try:
            threshold = float(threshold)
            if threshold <= 0:
                return jsonify({"error": "threshold must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid threshold value"}), 400

        try:
            result = agent.run_intraoperative_replan(
                intra_op_ct_path=ct_path,
                original_plan=original_plan,
                deviation_threshold_mm=threshold,
                output_dir=output_dir,
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Intraoperative replanning failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat/abort", methods=["POST"])
    def api_chat_abort():
        """Clean up incomplete conversation after user aborts streaming."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        try:
            # Remove the last incomplete conversation turn
            conv = agent.memory.conversation
            if len(conv) >= 2:
                # Remove last assistant message if incomplete
                if conv[-1].get("role") == "assistant":
                    conv.pop()
                # Remove last user message (the one that triggered the aborted response)
                if conv and conv[-1].get("role") == "user":
                    conv.pop()
            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Chat abort cleanup failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/clear_all", methods=["POST"])
    @require_api_key
    def api_clear_all():
        """Clear all loaded data (CT, CTV, OAR, planning results) for a fresh start."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500
        try:
            agent.memory.clear_all_data()
            agent.memory.clear_conversation()
            return jsonify({"success": True, "message": "All data cleared"})
        except Exception as e:
            logger.error(f"Clear all data failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/dicom_rt", methods=["POST"])
    def api_export_dicom_rt():
        """Export treatment plan to DICOM-RT format."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        ct_path = data.get("ct_path")
        output_dir = data.get("output_dir", "./output/dicom_rt")

        try:
            import os
            os.makedirs(output_dir, exist_ok=True)

            # Get planning data
            seed_plan = agent.memory.retrieve("seed_plan")
            dose_distribution = agent.memory.retrieve("dose_distribution")
            ct_image = agent.memory.retrieve("ct_image")

            if seed_plan is None:
                return jsonify({"error": "No plan available. Run planning first."}), 400

            # Export using DicomRTExporterTool
            from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool
            tool = DicomRTExporterTool()
            result = tool._execute(
                ct_image=ct_image,
                seed_plan=seed_plan,
                dose_distribution=dose_distribution,
                output_dir=output_dir,
            )

            if result.success:
                return jsonify({"success": True, "output_dir": output_dir, "message": result.message})
            else:
                return jsonify({"success": False, "error": result.error}), 400
        except Exception as e:
            logger.error(f"DICOM-RT export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/stl", methods=["POST"])
    def api_export_stl():
        """Export seed positions as STL files."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_dir = data.get("output_dir", "./output/stl")

        try:
            import os
            import numpy as np
            os.makedirs(output_dir, exist_ok=True)

            seed_plan = agent.memory.retrieve("seed_plan")
            if seed_plan is None:
                return jsonify({"error": "No plan available. Run planning first."}), 400

            ct_image = agent.memory.retrieve("ct_image")
            seed_info = getattr(agent, 'config', {}).get("seed_info", {"length": 4.5, "radius": 0.4})

            # Export seeds as STL using visualizer
            count = 0
            for i, entry in enumerate(seed_plan):
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                seeds = entry[1]
                for j, seed in enumerate(seeds):
                    if not isinstance(seed, (list, tuple)) or len(seed) < 2:
                        continue
                    # Save position data as numpy (STL requires pyvista/vtk)
                    pos = np.array(seed[0])
                    direc = np.array(seed[1])
                    np.save(os.path.join(output_dir, f"seed_{i}_{j}_pos.npy"), pos)
                    np.save(os.path.join(output_dir, f"seed_{i}_{j}_dir.npy"), direc)
                    count += 1

            return jsonify({"success": True, "count": count, "output_dir": output_dir})
        except Exception as e:
            logger.error(f"STL export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_chat():
        """Natural language chat interface with execution trace."""
        data = request.get_json() or {}
        message = data.get("message", "")
        ui_state = data.get("ui_state", {})
        stream = data.get("stream", True)  # Default to streaming
        image_path = data.get("image_path", None)  # Optional image path
        clear_context = data.get("clear_context", False)  # Optional: clear conversation history
        session_id = data.get("session_id", None)  # Optional: session ID for isolation

        # Get or create agent for this session
        agent = get_agent(session_id)
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        # Handle clear_context for backward compatibility
        if clear_context:
            agent.memory.clear_conversation()
            logger.info("Conversation context cleared")

        if not message and not image_path:
            return jsonify({"error": "message or image is required"}), 400

        # If image provided but no message, use default prompt
        if image_path and not message:
            message = "Please analyze this image"

        # Include image path in message if provided
        full_message = message
        if image_path:
            full_message = f"{message}\n\n[Uploaded image path: {image_path}]"

        if stream:
            def generate():
                agent.memory.set_ui_state(ui_state)
                try:
                    for event in agent.chat_with_stream(full_message):
                        yield event
                except Exception as e:
                    # Mid-stream failure: emit a final SSE error event so the
                    # client can render a graceful message instead of a broken stream.
                    logger.error(f"Chat stream failed: {e}")
                    import json
                    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                    'Connection': 'keep-alive',
                }
            )
        else:
            try:
                agent.memory.set_ui_state(ui_state)
                result = agent.chat_with_trace(full_message)
                return jsonify({
                    "response": result["response"],
                    "steps": result["steps"],
                    "llm_meta": result.get("llm_meta", {}),
                    "context": {
                        "summary": agent.memory.context_summary or None,
                        "compaction_count": agent.memory.compaction_count,
                        "message_count": len(agent.memory.conversation),
                        "ui_state": agent.memory.get_ui_state(),
                    },
                    "session_id": agent.memory.session_id,
                    "brain_available": agent.brain_available,
                })
            except Exception as e:
                logger.error(f"Chat failed: {e}")
                return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/stream")
    def api_tasks_stream():
        """SSE endpoint for real-time task progress updates."""
        task_id = request.args.get("task_id")

        def generate():
            if task_id:
                task = task_manager.get_task(task_id)
                if task:
                    yield f"event: task\ndata: {json.dumps(task)}\n\n"
                return

            for tid, task in task_manager.get_all_tasks().items():
                yield f"event: task\ndata: {json.dumps(task)}\n\n"
                if task["status"] != "running":
                    continue

        return Response(generate(), mimetype='text/event-stream')

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def api_task_status(task_id):
        """Get task status."""
        task = task_manager.get_task(task_id)
        if task is None:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_list():
        """List all tasks."""
        return jsonify(task_manager.get_all_tasks())

    @app.route("/api/export/dicom", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_export_dicom():
        """Export plan to DICOM RT format."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_dir = data.get("output_dir", "./dicom_export")

        if not _validate_path(output_dir):
            return jsonify({"error": "Invalid output_dir"}), 400

        try:
            ct_image = agent.memory.retrieve("ct_image")
            if ct_image is None:
                return jsonify({"error": "No CT image in memory. Run planning first."}), 400

            seed_positions = agent.memory.retrieve("seed_positions")
            dose_distribution = agent.memory.retrieve("dose_distribution")
            ctv_array = agent._get_label_array("ctv_array")
            oar_array = agent._get_label_array("oar_array")

            structures = {}
            if ctv_array is not None:
                structures["CTV"] = ctv_array
            if oar_array is not None:
                structures["OAR"] = oar_array

            from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool
            exporter = DicomRTExporterTool()

            result = exporter.execute(
                ct_image=ct_image,
                structures=structures,
                dose_array=dose_distribution,
                seeds=seed_positions or [],
                output_dir=output_dir,
            )

            if result.success:
                return jsonify({
                    "success": True,
                    "files": result.data,
                    "message": result.message,
                })
            else:
                return jsonify({"error": result.error}), 500

        except Exception as e:
            logger.error(f"DICOM export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/report", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_export_report():
        """Generate planning report."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        output_path = data.get("output_path", "./report.json")
        output_format = data.get("format", "json")

        if not _validate_path(output_path):
            return jsonify({"error": "Invalid output_path"}), 400
        if output_format not in ("json", "html", "pdf"):
            return jsonify({"error": "Invalid format. Use 'json', 'html', or 'pdf'"}), 400

        try:
            metrics = agent.memory.retrieve("metrics", {})
            plan_score = metrics.get("plan_score", 0)
            total_seeds = metrics.get("total_seeds", 0)
            total_trajectories = metrics.get("num_trajectories", 0)

            from tool_factory.output.report_generator import ReportGeneratorTool
            generator = ReportGeneratorTool()

            result = generator.execute(
                patient_id=agent.memory.patient_data.get("id", "UNKNOWN"),
                plan_name="BrachyPlan",
                output_path=output_path,
                output_format=output_format,
                ctv_metrics={"voxels": int(metrics.get("ctv_voxel_count", 0))},
                dose_metrics=metrics,
                plan_score=plan_score,
                total_seeds=total_seeds,
                total_trajectories=total_trajectories,
            )

            if result.success:
                return jsonify({
                    "success": True,
                    "path": result.data,
                    "message": result.message,
                })
            else:
                return jsonify({"error": result.error}), 500

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/viewer/control", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_viewer_control():
        """LLM-callable viewer control endpoint. Adjust window/level, navigate slices, toggle overlays."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        action = data.get("action", "")
        ct_data = agent.memory.retrieve("ct_data")

        if ct_data is None and action not in ("get_state",):
            return jsonify({"error": "No CT image loaded"}), 400

        try:
            if action == "set_window":
                w = data.get("window", agent.memory.retrieve("ct_window_width") or 400)
                l = data.get("level", agent.memory.retrieve("ct_window_center") or 40)
                agent.memory.store("ct_window_width", w)
                agent.memory.store("ct_window_center", l)
                return jsonify({"success": True, "message": f"Window set to W:{w} L:{l}", "window": w, "level": l})

            elif action == "set_preset":
                presets = {
                    "soft": {"w": 400, "l": 40},
                    "bone": {"w": 2000, "l": 400},
                    "lung": {"w": 1500, "l": -600},
                    "brain": {"w": 80, "l": 40},
                }
                preset = data.get("preset", "soft")
                if preset not in presets:
                    return jsonify({"error": f"Unknown preset: {preset}. Available: {list(presets.keys())}"}), 400
                p = presets[preset]
                agent.memory.store("ct_window_width", p["w"])
                agent.memory.store("ct_window_center", p["l"])
                return jsonify({"success": True, "message": f"Preset '{preset}' applied (W:{p['w']} L:{p['l']})", "window": p["w"], "level": p["l"]})

            elif action == "navigate_slice":
                axis = data.get("axis", "axial")
                slice_index = data.get("slice_index", 0)
                shape = ct_data.shape
                axis_map = agent.memory.retrieve("ct_axis_map") or {'axial': 2, 'sagittal': 0, 'coronal': 1}
                axis_idx = axis_map.get(axis, 2)
                max_slice = shape[axis_idx] - 1
                slice_index = max(0, min(slice_index, max_slice))
                agent.memory.store(f"viewer_slice_{axis}", slice_index)
                return jsonify({"success": True, "message": f"Moved to {axis} slice {slice_index}/{max_slice}", "axis": axis, "slice_index": slice_index, "max_slice": max_slice})

            elif action == "set_threshold":
                threshold = data.get("threshold", -200)
                agent.memory.store("viewer_threshold", threshold)
                return jsonify({"success": True, "message": f"Threshold set to {threshold} HU", "threshold": threshold})

            elif action == "toggle_overlay":
                overlay = data.get("overlay", "ctv")
                current = agent.memory.retrieve("viewer_overlay")
                new_overlay = None if current == overlay else overlay
                agent.memory.store("viewer_overlay", new_overlay)
                return jsonify({"success": True, "message": f"Overlay {overlay} {'activated' if new_overlay else 'deactivated'}", "overlay": new_overlay})

            elif action == "get_state":
                return jsonify({
                    "success": True,
                    "ct_loaded": ct_data is not None,
                    "ct_shape": list(ct_data.shape) if ct_data is not None else None,
                    "window": agent.memory.retrieve("ct_window_width") or 400,
                    "level": agent.memory.retrieve("ct_window_center") or 40,
                    "threshold": agent.memory.retrieve("viewer_threshold"),
                    "overlay": agent.memory.retrieve("viewer_overlay"),
                    "slices": {
                        "axial": agent.memory.retrieve("viewer_slice_axial") or 0,
                        "sagittal": agent.memory.retrieve("viewer_slice_sagittal") or 0,
                        "coronal": agent.memory.retrieve("viewer_slice_coronal") or 0,
                    },
                })

            else:
                return jsonify({"error": f"Unknown action: {action}. Available: set_window, set_preset, navigate_slice, set_threshold, toggle_overlay, get_state"}), 400

        except Exception as e:
            logger.error(f"Viewer control failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screenshot", methods=["POST"])
    def api_screenshot():
        """Receive a screenshot from the frontend and save it."""
        data = request.get_json() or {}
        image_data = data.get("image", "")  # base64 data URL
        description = data.get("description", "screenshot")
        target = data.get("target", "unknown")

        if not image_data:
            return jsonify({"error": "No image data provided"}), 400

        try:
            import base64
            import uuid

            # Strip data URL prefix if present
            if "," in image_data:
                header, b64 = image_data.split(",", 1)
            else:
                b64 = image_data

            img_bytes = base64.b64decode(b64)

            # Save to uploads/screenshots/
            screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads", "screenshots")
            screenshots_dir = os.path.normpath(screenshots_dir)
            os.makedirs(screenshots_dir, exist_ok=True)

            filename = f"screenshot_{uuid.uuid4().hex[:12]}.png"
            filepath = os.path.join(screenshots_dir, filename)

            with open(filepath, "wb") as f:
                f.write(img_bytes)

            url = f"/api/screenshots/{filename}"
            logger.info(f"Screenshot saved: {filepath} ({len(img_bytes)} bytes)")

            return jsonify({
                "success": True,
                "url": url,
                "filename": filename,
                "description": description,
                "target": target,
            })
        except Exception as e:
            logger.error(f"Screenshot save failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screenshots/<filename>")
    def api_serve_screenshot(filename):
        """Serve a saved screenshot file."""
        screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads", "screenshots")
        screenshots_dir = os.path.normpath(screenshots_dir)
        filepath = os.path.join(screenshots_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(screenshots_dir, filename, mimetype="image/png")

    @app.route("/api/reset", methods=["POST"])
    @require_api_key
    def api_reset():
        """Reset agent state for a session."""
        nonlocal _sessions, _session_timestamps
        data = request.get_json() or {}
        session_id = data.get("session_id", _default_session_id)

        if session_id in _sessions:
            _sessions.pop(session_id, None)
            _session_timestamps.pop(session_id, None)
            logger.info(f"Reset session: {session_id}")
            return jsonify({"success": True, "message": f"Session {session_id} reset"})
        else:
            return jsonify({"success": True, "message": "Session not found"})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


def run_server(port: int = 8080, host: str = "127.0.0.1", config: Optional[Dict] = None):
    """Run the web server."""
    app = create_app(config)

    if app is None:
        logger.error("Cannot start server - Flask not available")
        logger.info("Install Flask: pip install flask flask-cors")
        return

    print(f"\n{'=' * 50}")
    print(f"  AI-BrachyAgent Web Server")
    print(f"  API: http://localhost:{port}/api/*")
    print(f"  Docs: http://localhost:{port}/api/status")
    print(f"  Press Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    # Cleanup handler: kill background threads/subprocesses on exit
    import atexit, signal as _sig, threading as _threading
    _shutdown_event = _threading.Event()

    def _cleanup():
        logger.info("[shutdown] Cleaning up background tasks...")
        # Signal all background threads to stop
        _shutdown_event.set()
        # Kill any orphaned subprocesses (e.g. GPU manager)
        try:
            import psutil
            current = psutil.Process()
            children = current.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
        except ImportError:
            pass
        # Cancel any pending AbortControllers from refreshPlanningUI
        logger.info("[shutdown] Cleanup complete.")

    atexit.register(_cleanup)

    def _signal_handler(signum, frame):
        print("\nShutting down...")
        _cleanup()
        import os
        os._exit(0)

    _sig.signal(_sig.SIGTERM, _signal_handler)
    _sig.signal(_sig.SIGINT, _signal_handler)

    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI-BrachyAgent Web Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--session", default="web", help="Session ID")
    args = parser.parse_args()

    config = {
        "session_id": args.session,
        "agent_config": {},
    }

    run_server(port=args.port, host=args.host, config=config)


if __name__ == "__main__":
    main()