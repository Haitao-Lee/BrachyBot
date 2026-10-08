"""Independent synthetic pixel checks for binary and PNG viewer parity."""
import base64
from io import BytesIO
import json

from flask import Flask
import numpy as np
from PIL import Image
import pytest


class Memory:
    session_id = "synthetic"

    def __init__(self):
        self.values = {
            "ct_data": np.zeros((2, 3, 4), np.int16),
            "ct_spacing": [1, 1, 2],
            "ct_axis_map": {"axial": 0, "sagittal": 2, "coronal": 1},
            "ctv_array": np.ones((2, 3, 4), np.uint8),
            "oar_array": np.full((2, 3, 4), 7, np.uint16),
            "ctv_source": "manual_label", "oar_source": "uploaded_unknown",
            "organ_names": {7: "Synthetic OAR"},
        }

    def retrieve(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def viewer(monkeypatch):
    from web.routes import viewer_routes
    class Agent:
        memory = Memory()
        _workspace_ct_ready = _workspace_data_ready = True

        def _get_label_array(self, key):
            return self.memory.retrieve(key)

    agent = Agent()
    monkeypatch.setattr(viewer_routes, "require_api_key", lambda f: f)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda f: f)
    app = Flask(__name__)
    app.secret_key = "synthetic"
    viewer_routes.register_viewer_routes(app, lambda **_: agent, lambda *a, **k: None, lambda *a, **k: {})
    return app.test_client(), agent


def png(response):
    assert response.status_code == 200, response.json
    return np.asarray(Image.open(BytesIO(base64.b64decode(response.json['data'].split(',', 1)[1]))).convert('RGBA'))


@pytest.mark.parametrize("kind,label", [("ctv", 1), ("oar", 7)])
def test_per_label_color_opacity_and_hidden_empty_selection(viewer, kind, label):
    client, _ = viewer
    payload = {"axis": "axial", "slice_index": 0, "overlay_type": kind,
               "filter_labels": True, "visible_labels": [label],
               "label_colors": {str(label): [0,255,0]}, "label_opacities": {str(label): .25}}
    assert png(client.post('/api/viewer/overlay', json=payload))[0,0].tolist() == [0,255,0,64]
    payload['visible_labels'] = []
    assert not png(client.post('/api/viewer/overlay', json=payload)).any()


@pytest.mark.parametrize("axis,index", [("axial", 0), ("sagittal", 1), ("coronal", 1)])
@pytest.mark.parametrize("source", ["nnunet_pancreatic", "nnunet_head_neck_gtv", "manual_label", "classified"])
def test_binary_volume_and_png_resolve_identical_semantic_labels(viewer, axis, index, source):
    client, agent = viewer
    labels = np.zeros((2,3,4), np.uint8)
    labels[0, :, :2] = 1
    labels[1, :, :2] = 2
    labels[1, :, 2:] = 3
    agent.memory.values.update(ctv_array=labels, ctv_full_labels=labels, ctv_source=source)
    if source == 'classified':
        agent.memory.values.update(structure_registry_initialized=True,
            structure_base_ctv_array=labels, structure_base_ctv_full_labels=labels,
            structure_base_ctv_source='nnunet_head_neck_gtv',
            structure_base_oar_array=agent.memory.values['oar_array'],
            structure_deleted_ids=['structure:ctv:1'])
    response = client.get('/api/viewer/label_volume')
    assert response.status_code == 200, response.json
    shape = (2,3,4)
    ctv_bytes = int(response.headers['X-CTV-Size'])
    for kind in ('ctv', 'oar'):
        if kind == 'ctv':
            array = np.frombuffer(response.data[:ctv_bytes], np.uint8).reshape(shape)
        else:
            array = np.frombuffer(response.data[ctv_bytes:], '<u2').reshape(shape)
        colors = {str(label): [int(label)%256,99,100] for label in np.unique(array) if label > 0}
        image = png(client.post('/api/viewer/overlay', json={
            'axis':axis,'slice_index':index,'overlay_type':kind,'label_colors':colors,
            kind+'_opacity':1,
        }))
        expected = array[shape[0]-1-index] if axis == 'axial' else array[:,:,index] if axis == 'sagittal' else array[:,index,:]
        if axis != 'axial': expected = np.repeat(expected, 2, axis=0)
        np.testing.assert_array_equal(image[:,:,3]>0, expected>0)
        for label in np.unique(expected):
            if label > 0:
                np.testing.assert_array_equal(image[expected==label, :3], np.tile(colors[str(label)], (np.count_nonzero(expected==label),1)))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -2, 2, None, 'bad'])
def test_bad_opacity_cannot_wrap_or_crash(viewer, value):
    client, _ = viewer
    image = png(client.post('/api/viewer/overlay', json={'axis':'axial','overlay_type':'oar','label_opacities':{'7':value}}))
    assert image[0,0,3] in (0,128,255)


def test_invalid_axis_and_overlay_kind_have_explicit_client_error(viewer):
    client, _ = viewer
    assert client.post('/api/viewer/overlay', json={'axis':'oblique'}).status_code == 400
    assert client.post('/api/viewer/overlay', json={'overlay_type':'not-an-oar'}).status_code == 400


def test_existing_oar_visibility_contract_remains_available(viewer):
    client, _ = viewer
    assert not png(client.post('/api/viewer/overlay', json={'visible_organs':[]})).any()
