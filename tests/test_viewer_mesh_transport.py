import gzip
import json
import struct

import numpy as np
import pytest
from flask import Flask
from utils.display_paths import DisplayRoots
from web.viewer_mesh import guide_mesh_response, wants_binary_mesh, MESH_MIMETYPE


def test_binary_guide_roundtrip_matches_existing_float32_rendering_and_tokens():
    app = Flask(__name__)
    state = {'vertices': np.array([[.123456789, -12, 4], [1, 2, 3], [4, 5, 6]]),
             'faces': np.array([[0, 1, 2]])}
    payload = {'success': True, 'guide': {'path': '/tmp/case/guide.stl'},
               'guide_status': {'state': 'ready'}}
    for encoding in ('identity', 'gzip'):
        with app.test_request_context(headers={'Accept': MESH_MIMETYPE, 'Accept-Encoding': encoding}):
            assert wants_binary_mesh()
            response = guide_mesh_response(payload, state, DisplayRoots(workspace_root='/tmp/case'))
            assert response.mimetype == MESH_MIMETYPE
            raw = gzip.decompress(response.data) if encoding == 'gzip' else response.data
            assert raw[:8] == b'BBMESH1\0'
            length, vertices, faces = struct.unpack_from('<III', raw, 8)
            metadata = json.loads(raw[20:20+length])
            assert metadata['guide']['path'] == '<workspace>/guide.stl'
            offset = 20 + (length + 3) // 4 * 4
            positions = np.frombuffer(raw, '<f4', vertices*3, offset).reshape(-1, 3)
            triangles = np.frombuffer(raw, '<u4', faces*3, offset + vertices*12).reshape(-1, 3)
            np.testing.assert_array_equal(positions, np.asarray(state['vertices'], dtype=np.float32))
            np.testing.assert_array_equal(triangles, state['faces'])
            assert len(raw) == offset + vertices*12 + faces*12
    assert payload['guide']['path'] == '/tmp/case/guide.stl'


@pytest.mark.parametrize('accept', ['*/*', 'application/json', MESH_MIMETYPE + ';q=0,application/json'])
def test_existing_json_clients_keep_their_contract(accept):
    with Flask(__name__).test_request_context(headers={'Accept': accept}):
        assert not wants_binary_mesh()


def test_invalid_guide_geometry_is_not_sent_as_a_usable_mesh():
    with Flask(__name__).test_request_context():
        with pytest.raises(ValueError, match='invalid geometry'):
            guide_mesh_response({'success': True}, {'vertices': [[0, 1, 2]], 'faces': [[0, 1, 2]]}, DisplayRoots())
