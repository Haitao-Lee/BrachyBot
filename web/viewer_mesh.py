"""Render-only binary guide transport; persisted and manufacturing data stay intact.

BBMESH1: 8-byte magic, uint32 metadata length/vertex count/triangle count,
UTF-8 JSON metadata padded to four bytes, float32 XYZ, uint32 triangle indices.
The floats are exactly the float32 values already sent by guide_public_payload.
"""
import gzip
import json
import struct

import numpy as np
from flask import Response, request
from utils.display_paths import relativize_value

MESH_MIMETYPE = "application/vnd.brachybot.mesh"


def wants_binary_mesh():
    # Preserve the JSON contract for existing clients sending */*.
    return (MESH_MIMETYPE in request.headers.get("Accept", "")
            and request.accept_mimetypes[MESH_MIMETYPE] > 0)


def guide_mesh_response(payload, state, roots):
    vertices = np.asarray(state["vertices"], dtype="<f4").reshape(-1, 3)
    faces = np.asarray(state["faces"], dtype="<u4").reshape(-1, 3)
    if not np.isfinite(vertices).all() or (faces.size and faces.max() >= len(vertices)):
        raise ValueError("Guide mesh contains invalid geometry")
    # Only metadata enters the path sanitizer; numeric geometry has no paths.
    metadata = json.dumps(relativize_value(payload, roots), ensure_ascii=False,
                          separators=(",", ":"), default=str).encode("utf-8")
    body = (b"BBMESH1\0" + struct.pack("<III", len(metadata), len(vertices), len(faces))
            + metadata + b"\0" * (-len(metadata) % 4)
            + vertices.tobytes() + faces.tobytes())
    headers = {"Vary": "Accept, Accept-Encoding"}
    if request.accept_encodings["gzip"] > 0:
        body = gzip.compress(body, compresslevel=1, mtime=0)
        headers["Content-Encoding"] = "gzip"
    return Response(body, mimetype=MESH_MIMETYPE, headers=headers)
