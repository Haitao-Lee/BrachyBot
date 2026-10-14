"""Actual JSON boundary, not substitute clinical calculation."""
import json
import numpy as np
from web.planning_response import planning_response_metadata


def test_nested_dose_volumes_stay_out_of_button_response_without_losing_quality():
    volume = np.ones((9, 324, 324), np.float32)
    metadata = {'dose_components': {'implanted': {'status': 'ready',
        'dose_distribution_physical_gy': volume, 'source_count': np.int64(12)},
        'planned': {'dose_distribution_physical_gy': np.zeros_like(volume), 'source_count': 0}},
        'continuation_evaluation': {'v100': np.float32(1), 'new_sources': 0},
        'source_direction': [0., 1., 0.], 'array': volume,
        'unbounded_geometry': list(range(257))}
    projected = planning_response_metadata(metadata)
    assert projected['dose_components']['implanted'] == {'status': 'ready', 'source_count': 12}
    assert projected['dose_components']['planned'] == {'source_count': 0}
    assert projected['continuation_evaluation'] == {'v100': 1., 'new_sources': 0}
    assert projected['source_direction'] == [0., 1., 0.]
    assert 'array' not in projected and 'unbounded_geometry' not in projected
    json.dumps(projected, allow_nan=False)
    assert metadata['dose_components']['implanted']['dose_distribution_physical_gy'] is volume
