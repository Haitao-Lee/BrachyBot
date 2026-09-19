import numpy as np
import pytest
from web.surgical_guide import mesh_validation


@pytest.mark.parametrize('variant', ['closed', 'open', 'duplicate', 'reversed', 'random'])
def test_packed_edges_equal_reference_qa_without_mutating_geometry(monkeypatch, variant):
    vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],dtype=float)
    faces=np.array([[0,2,1],[0,1,3],[1,2,3],[2,0,3]],dtype=int)
    if variant=='open': faces=np.concatenate((faces[:-1],faces[:1]))
    if variant=='duplicate': faces=np.concatenate((faces,faces[:1]))
    if variant=='reversed': faces=faces[:,::-1]
    if variant=='random':
        rng=np.random.default_rng(17)
        vertices=rng.random((100,3));faces=rng.integers(0,100,size=(1000,3))
    original_v=vertices.copy();original_f=faces.copy()
    monkeypatch.setenv('BRACHYBOT_GUIDE_FAST_PATH','0')
    reference=mesh_validation(vertices,faces)
    monkeypatch.setenv('BRACHYBOT_GUIDE_FAST_PATH','1')
    assert mesh_validation(vertices,faces)==reference
    assert np.array_equal(vertices,original_v)
    assert np.array_equal(faces,original_f)
