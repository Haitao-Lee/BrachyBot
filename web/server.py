"""AI-BrachyAgent Web API Server.

The public entry point remains `python web/server.py`; shared helpers and route
groups live in smaller modules so each file is easier to audit.
"""

import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(WEB_DIR, ".."))

try:
    from web.server_support import (
        APP_DIR,
        DOSE_MODEL_SCALE_GY,
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )
    from web import server_support as _server_support
    from web.routes.viewer_routes import register_viewer_routes
    from web.routes.planning_routes import register_planning_routes
except ImportError:  # pragma: no cover - supports direct script execution.
    from server_support import (  # type: ignore
        APP_DIR,
        DOSE_MODEL_SCALE_GY,
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )
    import server_support as _server_support  # type: ignore
    from routes.viewer_routes import register_viewer_routes
    from routes.planning_routes import register_planning_routes

_TRUST_NETWORK = _server_support._TRUST_NETWORK
_is_loopback_host = _server_support._is_loopback_host
_validate_path = _server_support._validate_path
_validate_upload_name = _server_support._validate_upload_name


def create_app(config: Optional[Dict] = None):
    """Create and configure the Flask application."""
    try:
        from flask import Flask, request, jsonify, send_from_directory, Response
        from flask_cors import CORS
        from werkzeug.exceptions import RequestEntityTooLarge
        HAS_FLASK = True
    except ImportError:
        HAS_FLASK = False
        logger.warning("Flask not installed. API endpoints will not be available.")
        return None

    app = Flask(__name__, static_folder=APP_DIR, static_url_path="")
    # CORS: restrict to localhost by default. Trusted LAN mode permits
    # loopback/private-network browser origins, not arbitrary websites.
    _origin_env = os.environ.get("ALLOWED_ORIGINS")
    if _origin_env:
        _allowed_origins = [o.strip() for o in _origin_env.split(",") if o.strip()]
    elif _TRUST_NETWORK:
        _allowed_origins = [
            r"http://localhost(:\d+)?",
            r"http://127\.0\.0\.1(:\d+)?",
            r"http://10\.\d+\.\d+\.\d+(:\d+)?",
            r"http://192\.168\.\d+\.\d+(:\d+)?",
            r"http://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+(:\d+)?",
        ]
    else:
        _allowed_origins = [
            "http://localhost",
            "http://127.0.0.1",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    CORS(app, origins=_allowed_origins)
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(_error):
        return jsonify({
            "error": "Request entity too large",
            "max_bytes": app.config.get("MAX_CONTENT_LENGTH"),
        }), 413

    @app.errorhandler(500)
    def handle_internal_server_error(error):
        logger.error("Unhandled server error: %s", error, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    if config is None:
        config = {}

    # Session management: each session gets its own agent instance
    _sessions: Dict[str, Any] = {}  # session_id -> BrachyAgent
    _session_timestamps: Dict[str, float] = {}  # session_id -> last access time
    _sessions_lock = threading.RLock()
    _default_session_id = config.get("session_id", "web")
    _max_sessions = 50  # Maximum number of concurrent sessions
    _session_timeout = 3600  # Session timeout in seconds (1 hour)
    websocket_clients = []

    def get_agent(session_id: str = None):
        """Get or create an agent for the given session."""
        nonlocal _sessions, _session_timestamps

        if session_id is None:
            session_id = _default_session_id

        with _sessions_lock:
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
        with _sessions_lock:
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
    @require_api_key
    @rate_limit
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
            if len(files) > MAX_UPLOAD_FILES:
                return jsonify({"error": f"Too many files; max is {MAX_UPLOAD_FILES}"}), 400

            upload_dir = UPLOAD_DIR
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
                if not _validate_upload_name(filename):
                    return jsonify({"error": f"Unsupported upload type: {filename}"}), 400
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
                if not _validate_upload_name(leaf, dicom_series=True):
                    return jsonify({"error": f"Unsupported DICOM series file type: {leaf}"}), 400
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
    @require_api_key
    @rate_limit
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
    @require_api_key
    @rate_limit
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
        if not _validate_path(ct_path, purpose="read"):
            return jsonify({"error": "Invalid ct_path"}), 400
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
    def _build_report_interpretation(agent, language="zh"):
        """Generate source-aware report interpretation without local clinical verdicts."""
        dose = (agent.memory.retrieve("dose_metrics") or {}) if agent else {}
        prescribed = dose.get("prescribed_dose", DOSE_MODEL_SCALE_GY)
        try:
            from tool_factory.report_context import (
                build_report_context,
                format_prescription_rationale_markdown,
                format_tumor_assessment_markdown,
            )

            def _report_lookup(key, default=None):
                if not agent:
                    return default
                if key == "plan_config":
                    return agent.memory.retrieve(key) or getattr(agent, "config", {}) or default
                return agent.memory.retrieve(key, default)

            report_context = build_report_context(_report_lookup)
            tumor_assessment_md = format_tumor_assessment_markdown(report_context, language)
            prescription_rationale_md = format_prescription_rationale_markdown(report_context, language)
        except Exception as exc:
            logger.warning(f"Report context build failed: {exc}")
            tumor_assessment_md = ""
            prescription_rationale_md = ""
        metrics = [
            ("CTV V100", (dose.get("v100") * 100) if dose.get("v100") is not None else None, "%", 1),
            ("D90", dose.get("d90"), " Gy", 2),
            ("D95", dose.get("d95"), " Gy", 2),
            ("V150", (dose.get("v150") * 100) if dose.get("v150") is not None else None, "%", 1),
            ("V200", (dose.get("v200") * 100) if dose.get("v200") is not None else None, "%", 1),
            ("Conformity Index CI", dose.get("ci"), "", 3),
            ("Homogeneity Index HI", dose.get("hi"), "", 3),
            ("Gradient Index GI", dose.get("gi"), "", 3),
        ]

        lines = [
            "**Dosimetric Evaluation & Clinical Interpretation**",
            "",
            "This auto-filled interpretation reports observed metrics only. Clinical pass/fail decisions must cite `clinical_kb` evidence or explicit case `plan_config` constraints for the current tumor site.",
            "",
            "**Observed metrics**",
        ]
        for label, value, unit, digits in metrics:
            if value is None:
                continue
            try:
                lines.append(f"- {label}: {float(value):.{digits}f}{unit}.")
            except (TypeError, ValueError):
                lines.append(f"- {label}: {value}{unit}.")

        score = dose.get("plan_score")
        if score is not None:
            try:
                lines.append(f"- Internal plan score: {float(score):.0f}/100. Use as an advisory QA ranking signal, not clinical approval.")
            except (TypeError, ValueError):
                lines.append(f"- Internal plan score: {score}. Use as an advisory QA ranking signal, not clinical approval.")

        if tumor_assessment_md:
            lines.extend(["", tumor_assessment_md])
        if prescription_rationale_md:
            lines.extend(["", prescription_rationale_md])

        lines.extend([
            "",
            "**Required review before clinical use**",
            "- Retrieve site-specific target coverage and OAR tolerance criteria from `clinical_kb`, or provide them in `plan_config`.",
            "- Verify CTV/OAR masks, coordinate registration, needle feasibility, seed coordinates, DVH, and high-dose regions.",
            "- Perform independent dose verification and obtain radiation oncologist/physicist sign-off.",
            "",
            "_Generated by BrachyBot for planning review; not a signed treatment prescription._",
        ])
        safety = (
            "**Safety & Quality Control**\n\n"
            "- Verify seed activity, prescription dose, coordinate system, needle paths, and seed coordinates.\n"
            "- Review CTV/OAR masks, DVH, hot spots, and high-dose OAR regions.\n"
            "- Final clinical limits must come from retrieved knowledge-base/guideline evidence or explicit plan_config.\n"
            f"- Current report prescription dose: {prescribed:.1f} Gy."
        )
        return "\n".join(lines), safety

    @app.route("/api/report/auto-fill", methods=["POST"])
    @require_api_key
    @rate_limit
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

                try:
                    from tool_factory.report_context import build_report_context

                    def _report_lookup(key, default=None):
                        if key == "plan_config":
                            return agent.memory.retrieve(key) or getattr(agent, "config", {}) or default
                        return agent.memory.retrieve(key, default)

                    report_context = build_report_context(_report_lookup)
                    patch["case.tumorImagingAssessment"] = report_context.get("tumor_imaging", {})
                    patch["planning.prescriptionRationale"] = report_context.get("prescription_rationale", {})
                    provenance["derived"] += [
                        "case.tumorImagingAssessment",
                        "planning.prescriptionRationale",
                    ]
                except Exception as e:
                    logger.warning(f"report context patch failed: {e}")

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


    register_viewer_routes(app, get_agent, _load_ct_image, _extract_dicom_tags)
    register_planning_routes(app, get_agent, session_context={
        "sessions": _sessions,
        "session_timestamps": _session_timestamps,
        "sessions_lock": _sessions_lock,
        "default_session_id": _default_session_id,
    })

    @app.route("/api/reset", methods=["POST"])
    @require_api_key
    def api_reset():
        """Reset agent state for a session."""
        nonlocal _sessions, _session_timestamps
        data = request.get_json() or {}
        session_id = data.get("session_id", _default_session_id)

        with _sessions_lock:
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
    if not _is_loopback_host(host):
        allow_insecure = os.environ.get("BRACHYBOT_ALLOW_INSECURE_REMOTE", "").lower() in TRUE_VALUES
        if not os.environ.get("BRACHYBOT_API_KEY") and not allow_insecure:
            logger.error(
                "Refusing to bind BrachyBot to non-loopback host %s without BRACHYBOT_API_KEY. "
                "Set BRACHYBOT_API_KEY, bind to 127.0.0.1, or explicitly set "
                "BRACHYBOT_ALLOW_INSECURE_REMOTE=1 for local trusted networks.",
                host,
            )
            return

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
    import atexit, itertools as _itertools, signal as _sig, threading as _threading
    _shutdown_event = _threading.Event()
    _active_operations = {}  # op_id -> operation metadata
    _op_counter = _itertools.count(1)
    _ops_lock = _threading.RLock()
    _track_local = _threading.local()

    class _OperationContext:
        """Context manager to track ongoing operations."""
        def __init__(self, name):
            self.name = name
            self.op_id = None
            self._nested = False
        def __enter__(self):
            stack = getattr(_track_local, "stack", [])
            if self.name in stack:
                self._nested = True
                stack.append(self.name)
                _track_local.stack = stack
                logger.debug(f"[OP-TRACK] Nested '{self.name}' reuses active operation")
                return self

            with _ops_lock:
                self.op_id = next(_op_counter)
                _active_operations[self.op_id] = {
                    "name": self.name,
                    "started_at": time.time(),
                    "thread": _threading.current_thread().name,
                }
                logger.debug(f"[OP-TRACK] Added '{self.name}' to active operations: {get_active_operations()}")
            stack.append(self.name)
            _track_local.stack = stack
            return self
        def __exit__(self, *args):
            stack = getattr(_track_local, "stack", [])
            if stack:
                try:
                    stack.remove(self.name)
                except ValueError:
                    pass
                _track_local.stack = stack
            if self._nested:
                return False

            with _ops_lock:
                if self.op_id in _active_operations:
                    _active_operations.pop(self.op_id, None)
                    logger.debug(f"[OP-TRACK] Removed '{self.name}' from active operations: {get_active_operations()}")
                else:
                    logger.warning(f"[OP-TRACK] Tried to remove '{self.name}' but it wasn't active: {get_active_operations()}")
            return False

    def get_active_operations():
        """Get list of currently active operations."""
        with _ops_lock:
            now = time.time()
            return [
                {
                    "id": op_id,
                    "name": meta["name"],
                    "thread": meta["thread"],
                    "elapsed_sec": round(now - meta["started_at"], 1),
                }
                for op_id, meta in sorted(_active_operations.items())
            ]

    # Make operation tracking available globally
    import builtins
    builtins.track_operation = _OperationContext
    builtins.get_active_operations = get_active_operations

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

    _shutdown_requested = [False]  # Use list for closure mutability

    def _signal_handler(signum, frame):
        try:
            signal_name = _sig.Signals(signum).name
        except Exception:
            signal_name = str(signum)
        print(f"\nShutdown signal received ({signal_name}/{signum})...")

        active = get_active_operations()

        if active:
            _shutdown_requested[0] = True
            print(f"⚠ {len(active)} operation(s) in progress: {active}")
            print("  Shutdown deferred so the active medical workflow can finish.")
            print("  Stop again after the operation completes, or set BRACHYBOT_FORCE_SHUTDOWN_ON_SECOND_SIGNAL=1 to allow forced termination.")
            if os.environ.get("BRACHYBOT_FORCE_SHUTDOWN_ON_SECOND_SIGNAL", "").lower() in TRUE_VALUES:
                print("  Force-shutdown override is enabled; terminating active workflow.")
                _cleanup()
                print("✓ Forced shutdown complete.")
                raise SystemExit(1)
            return

        # No active operations, safe to shut down
        print("✓ No active operations. Shutting down gracefully...")
        print("  Waiting 3 seconds for pending HTTP responses...")
        import time
        time.sleep(3)

        _cleanup()
        print("✓ Shutdown complete.")
        raise SystemExit(0)

    _sig.signal(_sig.SIGTERM, _signal_handler)
    _sig.signal(_sig.SIGINT, _signal_handler)
    if hasattr(_sig, "SIGHUP"):
        _sig.signal(_sig.SIGHUP, _signal_handler)

    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI-BrachyAgent Web Server")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    default_host = "0.0.0.0" if (os.environ.get("BRACHYBOT_API_KEY") or os.environ.get("BRACHYBOT_TRUST_NETWORK")) else "127.0.0.1"
    parser.add_argument("--host", default=default_host, help="Server host")
    parser.add_argument("--session", default="web", help="Session ID")
    args = parser.parse_args()

    config = {
        "session_id": args.session,
        "agent_config": {},
    }

    run_server(port=args.port, host=args.host, config=config)


if __name__ == "__main__":
    main()
