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

API_KEY = os.environ.get("BRACHYBOT_API_KEY", None)
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

    Allows absolute paths (required for CT image paths) but rejects
    paths containing '..' traversal components.
    Check BEFORE normpath resolves them, so raw '..' segments are caught.
    """
    if not path:
        return False
    # Check raw segments BEFORE normpath resolves '..' away
    if '..' in path.replace('\\', '/').split('/'):
        return False
    return True


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY:
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
    CORS(app)
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload

    if config is None:
        config = {}

    agent = None
    websocket_clients = []

    def get_agent():
        nonlocal agent
        if agent is None:
            try:
                from AgenticSys import BrachyAgent
                agent = BrachyAgent(
                    session_id=config.get("session_id", "web"),
                    config=config.get("agent_config", {})
                )
                logger.info("BrachyAgent initialized for web server")
            except Exception as e:
                import traceback
                logger.error(f"Failed to initialize BrachyAgent: {e}")
                logger.error(traceback.format_exc())
                return None
        return agent

    @app.route("/")
    def index():
        return send_from_directory(APP_DIR, "index.html")

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        """Upload a file to the server and return the server-side path."""
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        # Sanitize filename
        filename = "".join(c for c in file.filename if c.isalnum() or c in "._- ")
        if not filename:
            filename = "uploaded_file"

        # Avoid overwriting: add timestamp
        base, ext = os.path.splitext(filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = f"{base}_{timestamp}{ext}"
        save_path = os.path.join(upload_dir, save_name)

        file.save(save_path)
        abs_path = os.path.abspath(save_path)

        return jsonify({
            "success": True,
            "path": abs_path,
            "filename": save_name,
            "size": os.path.getsize(abs_path),
        })

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

        try:
            import numpy as np
            import SimpleITK as sitk

            logger.info(f"Loading CT from: {ct_path}")
            ct_sitk = sitk.ReadImage(ct_path)
            
            # Reorient to LPI (Left-Posterior-Inferior) standard anatomical orientation
            ct_oriented = sitk.DICOMOrient(ct_sitk, 'LPI')
            logger.info(f"Reoriented to LPI")
            
            ct_data = sitk.GetArrayFromImage(ct_oriented)  # Shape: (Z, Y, X) in LPI orientation
            spacing = ct_oriented.GetSpacing()  # (X, Y, Z)
            shape = ct_data.shape
            logger.info(f"CT shape after orientation (ZYX): {shape}, spacing (XYZ): {spacing}")

            # Store in agent memory
            agent.memory.store("ct_image", ct_oriented)
            agent.memory.store("ct_data", ct_data)
            agent.memory.store("ct_spacing", spacing)
            agent.memory.store("ct_shape", list(shape))
            agent.memory.store("ct_window_center", window_center)
            agent.memory.store("ct_window_width", window_width)

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

            return jsonify({
                "success": True,
                "slices": slices,
                "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
                "shape": [int(shape[0]), int(shape[1]), int(shape[2])],
                "hu_range": [float(ct_data.min()), float(ct_data.max())],
            })
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
            
            if axis_name == 'sagittal':
                slice_data = slice_data.T
            elif axis_name == 'coronal':
                slice_data = slice_data.T

            # Apply threshold overlay if requested
            if threshold is not None:
                mask = ct_data > threshold
                mask_slice = np.take(mask, slice_index, axis=axis)
                if axis_name in ('sagittal', 'coronal'):
                    mask_slice = mask_slice.T
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
                mask_data = agent.memory.retrieve("ctv_array")
            else:
                mask_data = agent.memory.retrieve("oar_array")

            if mask_data is None:
                img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                return jsonify({"success": True, "data": f"data:image/png;base64,{img_str}", "has_mask": False})

            # Extract slice from mask: np.take with axis gives correct orientation
            # mask_data is (Z, Y, X), axis_map: axial=0(Z), sagittal=2(X), coronal=1(Y)
            mask_slice = np.take(mask_data, slice_index, axis=axis)

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
                overlay[mask_slice > 0] = [255, 0, 0, alpha]
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
            oar_array = agent.memory.retrieve("oar_array")
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
            from scipy.ndimage import binary_closing, binary_fill_holes

            # Get mask data
            if source == "ctv":
                mask_data = agent.memory.retrieve("ctv_array")
            else:
                mask_data = agent.memory.retrieve("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract specific label if provided
            if label_id is not None:
                mask = (mask_data == int(label_id)).astype(np.uint8)
            else:
                mask = (mask_data > 0).astype(np.uint8)

            if mask.sum() == 0:
                return jsonify({"error": "Empty mask"}), 400

            # Clean up mask
            mask = binary_closing(mask, iterations=1).astype(np.uint8)
            mask = binary_fill_holes(mask).astype(np.uint8)

            spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
            spacing = tuple(float(s) for s in spacing[:3])

            vertices, faces, normals, values = measure.marching_cubes(
                mask, level=0.5, spacing=spacing, allow_degenerate=False
            )

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
        smoothing = data.get("smoothing", 1)

        if label_id is None:
            return jsonify({"error": "label_id required"}), 400

        try:
            import numpy as np
            from skimage import measure
            from scipy.ndimage import binary_closing, binary_fill_holes

            if source == "ctv":
                mask_data = agent.memory.retrieve("ctv_array")
            else:
                mask_data = agent.memory.retrieve("oar_array")

            if mask_data is None:
                return jsonify({"error": f"No {source} mask data available"}), 400

            # Extract binary mask for this label
            label_id = int(label_id)
            binary_mask = (mask_data == label_id).astype(np.uint8)

            if binary_mask.sum() == 0:
                return jsonify({"error": f"Label {label_id} not found in mask"}), 400

            # Clean up mask
            binary_mask = binary_closing(binary_mask, iterations=smoothing).astype(np.uint8)
            binary_mask = binary_fill_holes(binary_mask).astype(np.uint8)

            # Get spacing from CT data
            spacing = agent.memory.retrieve("ct_spacing") or (1.0, 1.0, 1.0)
            # Ensure spacing is tuple of 3 floats
            if isinstance(spacing, (list, tuple)) and len(spacing) >= 3:
                spacing = tuple(float(s) for s in spacing[:3])
            else:
                spacing = (1.0, 1.0, 1.0)

            # Generate mesh with marching cubes
            vertices, faces, normals, values = measure.marching_cubes(
                binary_mask, level=0.5, spacing=spacing, allow_degenerate=False
            )

            # Simple decimation: if too many faces, use quadric decimation
            if len(faces) > 50000:
                target = min(50000, len(faces))
                # Use Open3D if available for proper decimation
                try:
                    import open3d as o3d
                    mesh_o3d = o3d.geometry.TriangleMesh()
                    mesh_o3d.vertices = o3d.utility.Vector3dVector(vertices)
                    mesh_o3d.triangles = o3d.utility.Vector3iVector(faces)
                    mesh_o3d = mesh_o3d.simplify_quadric_decimation(target_number_of_triangles=target)
                    vertices = np.asarray(mesh_o3d.vertices)
                    faces = np.asarray(mesh_o3d.triangles)
                except ImportError:
                    # Fallback: stride-based decimation
                    stride = max(1, len(faces) // target)
                    faces = faces[::stride]

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

    @app.route("/api/config", methods=["POST"])
    def api_config():
        """Update agent configuration (hyperparameters)."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}

        try:
            if "seed_info" in data:
                agent.config["seed_info"] = data["seed_info"]
            if "radiation_array_params" in data:
                agent.config["radiation_array_params"] = data["radiation_array_params"]
            if "reference_direc" in data:
                agent.config["reference_direc"] = data["reference_direc"]
            if "in_lowest_energy" in data:
                agent.config["in_lowest_energy"] = data["in_lowest_energy"]
            if "out_highest_energy" in data:
                agent.config["out_highest_energy"] = data["out_highest_energy"]
            if "DVH_rate" in data:
                agent.config["DVH_rate"] = data["DVH_rate"]
            if "max_iter" in data:
                agent.config["max_iter"] = data["max_iter"]
            if "rf_params" in data:
                agent.config["rf_params"] = data["rf_params"]

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

    @app.route("/api/chat", methods=["POST"])
    @require_api_key
    @rate_limit
    def api_chat():
        """Natural language chat interface with execution trace."""
        agent = get_agent()
        if agent is None:
            return jsonify({"error": "Agent not available"}), 500

        data = request.get_json() or {}
        message = data.get("message", "")
        ui_state = data.get("ui_state", {})
        stream = data.get("stream", True)  # Default to streaming
        image_path = data.get("image_path", None)  # Optional image path
        clear_context = data.get("clear_context", False)  # Optional: clear conversation history
        session_id = data.get("session_id", None)  # Optional: session ID for isolation

        # Handle session isolation for benchmarks
        if session_id:
            # If session ID changed, always clear context for fresh start
            if not hasattr(agent, '_current_session_id') or agent._current_session_id != session_id:
                agent.memory.clear_conversation()
                agent._current_session_id = session_id
                logger.info(f"New session started: {session_id}")
        elif clear_context:
            # Clear conversation context if requested (for fresh start between tests)
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
                for event in agent.chat_with_stream(full_message):
                    yield event

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
            ctv_array = agent.memory.retrieve("ctv_array")
            oar_array = agent.memory.retrieve("oar_array")

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

    @app.route("/api/reset", methods=["POST"])
    @require_api_key
    def api_reset():
        """Reset agent state."""
        nonlocal agent
        agent = None
        return jsonify({"success": True, "message": "Agent reset"})

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