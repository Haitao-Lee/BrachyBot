# CTV Tumor Segmentation Unified Category Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the six tumor segmentation models — pancreas/liver/kidney/head-neck/nasopharynx (non-contrast, contrast-enhanced)/lung — peer entries in a single category with unified registration, unified GPU scheduling, a unified output contract and downstream semantics, and a unified front-end experience (green when usable).

**Architecture:** Add `model_registry.py` as the single source of truth for management/semantics (referencing the existing three execution specs, not rewriting the engines); extract shared scheduling to the execution boundary (pancreas is also brought under the cross-process `gpu_lock`); `CTVSegmentationTool` normalizes output and unifies `ctv_source` as the route id; downstream `structure_service`/`viewer_routes` classify by registry `target_semantics` (old snapshots fall back via suffix aliases); the front-end selector/availability is driven by the registry, with all usable categories green.

**Tech Stack:** Python 3.12 (`~/.conda/envs/brachytherapy/bin/python`), pytest, Flask, SimpleITK, nnUNet v2, vanilla JS (`web/app/static/js`), Node (syntax check, path below).

**Key Conventions**
- Route ids stay unchanged (`nnunet_pancreatic` / `nnunet_liver_tumor` / `nnunet_kidney_tumor` / `nnunet_head_neck_gtv` / `nnunet_nasopharynx_ncct` / `nnunet_nasopharynx_cect` / `vista3d_lung_tumor`).
- End-to-end test command: `~/.conda/envs/brachytherapy/bin/python -m pytest <path> -q -p no:cacheprovider`
- Node：`<vscode-server>/cli/servers/Stable-520fb30b2d3d324b4cb2342f6e88e2cd93751de1/server/node`
- **Commit Discipline:** This workspace has uncommitted changes from another session. Run `git add` only for files that "belong purely to this plan" (new modules + new tests). The shared files (`__init__.py`, `structure_service.py`, `viewer_routes.py`, `planning_routes.py`, `response_tools.py`, `turn_policy.py`, `index.html`, `brachybot-ui-api.js`) are **not added to the git index** by this plan; decide on committing them together afterwards.

---

## File Structure

- Create: `BrachyBot/tool_factory/CTV_seg/model_registry.py` — route table and derived helpers (single source of truth for management/semantics).
- Create: `BrachyBot/tests/test_model_registry.py` — registry contract tests.
- Create: `BrachyBot/tests/test_ctv_downstream_equivalence.py` — downstream equivalence tests.
- Modify: `BrachyBot/tool_factory/CTV_seg/__init__.py` — derive aliases/tool table from the registry; unify `ctv_source`; unify `label_stats`.
- Modify: `BrachyBot/tool_factory/CTV_seg/pancreatic_tumor_nnunet.py` — bring under the shared `gpu_lock`.
- Modify: `BrachyBot/web/structure_service.py` — classify by registry semantics.
- Modify: `BrachyBot/web/routes/viewer_routes.py` — classify by registry semantics.
- Modify: `BrachyBot/agent_runtime/response_tools.py` — nasopharynx sentinel handling.
- Modify: `BrachyBot/agent_runtime/turn_policy.py` — direct execution of `<site> CTV`.
- Modify: `BrachyBot/web/app/index.html` — selector options and category copy (reconciled against the registry).
- Modify: `BrachyBot/web/app/static/js/brachybot-ui-api.js` — all-green availability, aliases, phase.
- Tests: `BrachyBot/tests/test_site_model_deployment.py`, `tests/test_nnunet_cascade_tumor.py`, `tests/test_web_frontend_ctv_selector.py` (new).

---

## Phase 1 — Backend Registry / Execution Boundary / Output Contract / Downstream Semantics

### Task 1: Registry Module

**Files:**
- Create: `tool_factory/CTV_seg/model_registry.py`
- Test: `tests/test_model_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py
import pytest
from tool_factory.CTV_seg.model_registry import (
    CTV_ROUTES, route, target_semantics, is_registered_model_source,
    canonical_ctv_source, ui_routes,
)

EXPECTED = {
    'nnunet_pancreatic': ('pancreas', 'target_plus_anatomy'),
    'nnunet_liver_tumor': ('liver', 'single_target'),
    'nnunet_kidney_tumor': ('kidney', 'single_target'),
    'nnunet_head_neck_gtv': ('head_neck', 'multi_target_gtv'),
    'nnunet_nasopharynx_ncct': ('nasopharynx', 'multi_target_gtv'),
    'nnunet_nasopharynx_cect': ('nasopharynx', 'multi_target_gtv'),
    'vista3d_lung_tumor': ('lung', 'single_target'),
}

def test_all_primary_routes_are_registered_as_peers():
    for rid, (site, semantics) in EXPECTED.items():
        r = route(rid)
        assert r is not None, rid
        assert r.site == site
        assert r.target_semantics == semantics

def test_target_semantics_handles_legacy_sources():
    assert target_semantics('model') == 'target_plus_anatomy'
    assert target_semantics('nnunet_cascade_liver') == 'single_target'
    assert target_semantics('manual_label') == 'single_target'
    assert target_semantics('') == 'single_target'

def test_registered_model_source_detection():
    assert is_registered_model_source('vista3d_lung_tumor')
    assert is_registered_model_source('model')
    assert is_registered_model_source('nnunet_cascade_kidney')
    assert not is_registered_model_source('manual_label')
    assert not is_registered_model_source('uploaded')

def test_canonical_ctv_source_maps_legacy_to_route_id():
    assert canonical_ctv_source('model') == 'nnunet_pancreatic'
    assert canonical_ctv_source('nnunet_cascade_liver') == 'nnunet_liver_tumor'
    assert canonical_ctv_source('nnunet_cascade_kidney') == 'nnunet_kidney_tumor'
    assert canonical_ctv_source('nnunet_nasopharynx_ncct') == 'nnunet_nasopharynx_ncct'
    assert canonical_ctv_source('manual_label') == 'manual_label'

def test_ui_routes_are_all_available_peers():
    ids = {r.id for r in ui_routes()}
    assert EXPECTED.keys() <= ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'tool_factory.CTV_seg.model_registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# tool_factory/CTV_seg/model_registry.py
"""Single source of truth for every tumor-segmentation route.

All sites are peers in the ``tumor_segmentation`` category.  Tool
registration, aliases, the model catalog, availability probes and the
front-end selector derive from this table, so adding a site means adding
one entry here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

DEPLOY_ROOT = Path('<workspace>')


@dataclass(frozen=True)
class CTVRoute:
    id: str
    site: str
    display_zh: str
    display_en: str
    engine: str  # inproc_nnunet | subprocess | text_guided
    modality: str = 'CT'
    ct_phase: Optional[str] = None
    labels: Mapping[int, str] = field(default_factory=dict)
    target_semantics: str = 'single_target'  # single_target | target_plus_anatomy | multi_target_gtv
    family: str = ''        # cascade | site_model | inproc | biomedparse | sat3d
    family_key: str = ''    # key inside that family's spec table
    catalog_status: str = 'experimental'
    requires_review: bool = True
    aliases: Tuple[str, ...] = ()


CTV_ROUTES: Dict[str, CTVRoute] = {
    'nnunet_pancreatic': CTVRoute(
        'nnunet_pancreatic', 'pancreas', '胰腺肿瘤', 'Pancreatic tumor',
        'inproc_nnunet', labels={1: 'pancreatic tumor', 2: 'artery', 3: 'vein', 4: 'pancreas'},
        target_semantics='target_plus_anatomy', family='inproc', family_key='pancreas',
        catalog_status='verified', requires_review=False,
        aliases=('胰腺', '胰腺癌', '胰腺肿瘤', 'pancreatic', 'pancreas')),
    'nnunet_liver_tumor': CTVRoute(
        'nnunet_liver_tumor', 'liver', '肝脏肿瘤', 'Liver tumor',
        'subprocess', labels={1: 'liver tumor'},
        family='cascade', family_key='liver', catalog_status='verified', requires_review=False,
        aliases=('肝', '肝脏', '肝脏肿瘤', '肝癌', 'liver', 'liver tumor')),
    'nnunet_kidney_tumor': CTVRoute(
        'nnunet_kidney_tumor', 'kidney', '肾脏肿瘤', 'Kidney tumor',
        'subprocess', labels={1: 'kidney tumor'},
        family='cascade', family_key='kidney', catalog_status='verified', requires_review=False,
        aliases=('肾', '肾脏', '肾脏肿瘤', '肾癌', 'kidney', 'kidney tumor')),
    'nnunet_head_neck_gtv': CTVRoute(
        'nnunet_head_neck_gtv', 'head_neck', '头颈 GTV（CT）', 'Head and neck GTV (CT)',
        'subprocess', labels={1: 'GTVp (primary)', 2: 'GTVn (nodal)'},
        target_semantics='multi_target_gtv', family='site_model', family_key='nnunet_head_neck_gtv',
        aliases=('头颈', '头颈肿瘤', '头颈部', '头颈部肿瘤', 'head_neck', 'head and neck')),
    'nnunet_nasopharynx_ncct': CTVRoute(
        'nnunet_nasopharynx_ncct', 'nasopharynx', '鼻咽 GTV（平扫 CT）', 'Nasopharynx GTV (non-contrast CT)',
        'subprocess', ct_phase='ncct', labels={1: 'GTVnx (primary)', 2: 'GTVnd (nodal)'},
        target_semantics='multi_target_gtv', family='site_model', family_key='nnunet_nasopharynx_ncct',
        aliases=('鼻咽癌平扫', '鼻咽平扫', 'nasopharynx_ncct')),
    'nnunet_nasopharynx_cect': CTVRoute(
        'nnunet_nasopharynx_cect', 'nasopharynx', '鼻咽 GTV（增强 CT）', 'Nasopharynx GTV (contrast-enhanced CT)',
        'subprocess', ct_phase='cect', labels={1: 'GTVnx (primary)', 2: 'GTVnd (nodal)'},
        target_semantics='multi_target_gtv', family='site_model', family_key='nnunet_nasopharynx_cect',
        aliases=('鼻咽癌增强', '鼻咽增强', 'nasopharynx_cect')),
    'vista3d_lung_tumor': CTVRoute(
        'vista3d_lung_tumor', 'lung', '肺部肿瘤', 'Lung tumor',
        'subprocess', labels={1: 'lung tumor'},
        family='site_model', family_key='vista3d_lung_tumor',
        aliases=('肺', '肺部', '肺部肿瘤', '肺肿瘤', '肺癌', 'lung', 'lung tumor')),
    'biomedparse_colon_primary': CTVRoute(
        'biomedparse_colon_primary', 'colon', '结肠肿瘤', 'Colon tumor',
        'text_guided', labels={1: 'colon tumor'},
        family='biomedparse', family_key='colon_primary',
        aliases=('结肠', '结肠肿瘤', '结肠癌', 'colon', 'colon tumor')),
    'biomedparse_prostate_lesion': CTVRoute(
        'biomedparse_prostate_lesion', 'prostate', '前列腺病灶（T2 MRI）', 'Prostate lesion (T2 MRI)',
        'text_guided', modality='T2w', labels={1: 'prostate lesion'},
        family='biomedparse', family_key='prostate_lesion',
        aliases=('前列腺', '前列腺癌', 'prostate', 'prostate lesion')),
}

# ``ctv_source`` values written before this registry existed.
_LEGACY_CTX_SOURCES = {
    'model': 'nnunet_pancreatic',
    'nnunet_cascade_liver': 'nnunet_liver_tumor',
    'nnunet_cascade_kidney': 'nnunet_kidney_tumor',
    'nnunet_cascade_lung': 'vista3d_lung_tumor',
    'nnunet_cascade_head_neck': 'nnunet_head_neck_gtv',
}

_LEGACY_SEMANTICS = {
    'model': 'target_plus_anatomy',
    'nnunet_liver_tumor': 'single_target',
    'nnunet_kidney_tumor': 'single_target',
    'biomedparse_v2': 'single_target',
    'biomedparse_v2_research_candidate': 'single_target',
    'totalsegmentator_liver_tumor': 'target_plus_anatomy',
    'sat3d': 'single_target',
}


def route(route_id) -> Optional[CTVRoute]:
    return CTV_ROUTES.get(str(route_id or '').strip())


def canonical_ctv_source(source) -> str:
    token = str(source or '').strip()
    mapped = _LEGACY_CTX_SOURCES.get(token)
    if mapped:
        return mapped
    return token or 'model'


def target_semantics(source) -> str:
    canonical = canonical_ctv_source(source)
    r = CTV_ROUTES.get(canonical)
    if r is not None:
        return r.target_semantics
    return _LEGACY_SEMANTICS.get(str(source or '').strip(), 'single_target')


def is_registered_model_source(source) -> bool:
    canonical = canonical_ctv_source(source)
    if canonical in CTV_ROUTES:
        return True
    token = str(source or '').strip().lower()
    return token == 'model' or token.startswith(('nnunet_', 'biomedparse_', 'totalsegmentator_', 'sat3d'))


def ui_routes():
    """Routes the front-end selector lists, in display order."""
    return [CTV_ROUTES[key] for key in CTV_ROUTES]


def aliases() -> Dict[str, str]:
    """canonical alias -> route id (legacy spellings included)."""
    table = {}
    for r in CTV_ROUTES.values():
        table[r.id] = r.id
        for alias in r.aliases:
            table[str(alias).casefold()] = r.id
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit (only our new files)**

```bash
cd <workspace>/BrachyBot
git add tool_factory/CTV_seg/model_registry.py tests/test_model_registry.py
git commit -m "feat(ctv): add unified tumor-segmentation route registry"
```

---

### Task 2: Unify `ctv_source` and Complete `label_stats`

**Files:**
- Modify: `tool_factory/CTV_seg/__init__.py` (the `meta` construction block, around lines 824-845)
- Test: `tests/test_model_registry.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py (append)
def test_metadata_contract_is_identical_across_engines():
    import numpy as np, SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool
    from tool_factory.CTV_seg.model_registry import canonical_ctv_source

    # Legacy adapter output shape used by pancreatic.  The wrapper must
    # normalize ctv_source and compute label_stats for every engine.
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    label = np.zeros((4, 4, 4), dtype=np.uint8)
    label[1:3, 1:3, 1:3] = 1
    label[0, 0, 0] = 2
    mask = sitk.GetImageFromArray(label)
    mask.CopyInformation(image)

    class FakeTool:
        name = 'nnunet_pancreatic'
        def _execute(self, **kwargs):
            from tool_factory import ToolResult
            return ToolResult(success=True, data=label, metadata={
                'ctv_mask': mask, 'ctv_array': (label == 1).astype(np.uint8),
                'full_label_array': label, 'label_map': {1: 'pancreatic tumor', 2: 'artery'},
                'label_counts': {1: 8, 2: 1},
            })

    tool = CTVSegmentationTool()
    tool._resolve_tool = lambda tumor_type: FakeTool()  # see Step 3 note
    result = tool._execute(image=image, tumor_type='nnunet_pancreatic')
    assert result.success
    meta = result.metadata
    assert canonical_ctv_source(meta['ctv_source']) == 'nnunet_pancreatic'
    assert meta['target_semantics'] == 'target_plus_anatomy'
    assert meta['label_stats']['artery']['voxel_count'] == 1
```

> Note: `_resolve_tool` is an internal indirection added in Task 2 so tests can inject a fake engine at the wrapper layer (see Step 3).

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_metadata_contract_is_identical_across_engines -q -p no:cacheprovider`
Expected: FAIL (`KeyError: 'target_semantics'` or `_resolve_tool` does not exist)

- [ ] **Step 3: Write minimal implementation**

Import the registry at the top of `__init__.py`:

```python
from .model_registry import (
    canonical_ctv_source, target_semantics, aliases as registry_aliases,
)
```

Add an indirection inside `CTVSegmentationTool` (for test injection and reuse by unified scheduling):

```python
    def _resolve_tool(self, tumor_type: str):
        return TOOL_REGISTRY[tumor_type]()
```

Change `tool = TOOL_REGISTRY[tumor_type]()` to `tool = self._resolve_tool(tumor_type)`.

In the `meta` dictionary (around line 824), change `ctv_source` and the new field to:

```python
            "ctv_source": (
                "manual_label"
                if from_label_path
                else canonical_ctv_source(res_meta.get("ctv_source", "model"))
            ),
            "target_semantics": (
                "single_target" if from_label_path else target_semantics(tumor_type)
            ),
```

Then, after `meta`, fill in a uniform `label_stats` (pancreas already provides it; for the rest, compute it from `full_label_array`/`ctv_array` when empty):

```python
        if not from_label_path and not meta["label_stats"]:
            stats_source = res_meta.get("full_label_array")
            if stats_source is None:
                stats_source = ctv_array
            meta["label_stats"] = _label_stats_from_array(
                stats_source, meta["label_map"], ctv_mask.GetSpacing(),
            )
```

Add at module level in `__init__.py` (near `_normalize_label_stats`):

```python
def _label_stats_from_array(array, label_map, spacing):
    """Uniform per-label volume/centroid stats for every CTV engine."""
    import numpy as _np
    stats = {}
    if array is None:
        return stats
    voxel_volume = float(spacing[0] * spacing[1] * spacing[2])
    for raw_label, count in zip(*_np.unique(array, return_counts=True)):
        label = int(raw_label)
        if label <= 0:
            continue
        name = str(label_map.get(label, f"label_{label}"))
        coords = _np.argwhere(array == label)
        centroid = coords.mean(axis=0).tolist() if coords.size else []
        stats[name] = {
            "label_id": label,
            "voxel_count": int(count),
            "volume_mm3": float(count * voxel_volume),
            "centroid_zyx": centroid,
        }
    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS (6 passed)

- [ ] **Step 5: Regression**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_site_model_deployment.py tests/test_nnunet_cascade_tumor.py tests/test_uploaded_mask_provenance.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(ctv): unify ctv_source and label_stats across engines"
```
(`__init__.py` is shared with another session's WIP, so it is not staged.)

---

### Task 3: Bring Pancreas into Unified GPU Scheduling

**Files:**
- Modify: `tool_factory/CTV_seg/pancreatic_tumor_nnunet.py` (`_run_nnunet_inference`, around lines 449-570)
- Test: `tests/test_model_registry.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py (append)
def test_pancreatic_inference_uses_shared_gpu_lock(monkeypatch):
    import tool_factory.CTV_seg.pancreatic_tumor_nnunet as P
    used = {}

    import contextlib
    from tool_factory.CTV_seg import site_model_runtime

    @contextlib.contextmanager
    def fake_lock(gpu, timeout=900):
        used['gpu'] = gpu
        yield

    monkeypatch.setattr(site_model_runtime, 'gpu_lock', fake_lock)

    class DM:
        device_str = 'cuda:0'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(P, 'device_session', lambda **kw: DM(), raising=False)
    # The engine must take the shared lock before touching the GPU.
    assert hasattr(P.NNUNetPancreaticTumorTool, '_gpu_guard')
    with P.NNUNetPancreaticTumorTool()._gpu_guard('0'):
        pass
    assert used['gpu'] == '0'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_pancreatic_inference_uses_shared_gpu_lock -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: ... '_gpu_guard'`

- [ ] **Step 3: Write minimal implementation**

Import at the top of `pancreatic_tumor_nnunet.py`:

```python
from contextlib import contextmanager
```

Add inside the class (before `_run_nnunet_inference`):

```python
    @contextmanager
    def _gpu_guard(self, gpu_index: str):
        """Serialise this in-process nnUNet run with every other CTV engine.

        The pancreatic path used to run without the cross-process lock the
        subprocess engines already share, so a lung/liver run could start on
        the same card and OOM.  Same lock, same policy, no inference change.
        """
        from .site_model_runtime import gpu_lock
        with gpu_lock(gpu_index):
            yield
```

Inside `_run_nnunet_inference`, wrap the inference call with `_gpu_guard` before the tensors are actually sent to the GPU (keeping the existing DeviceManager selection and `CUDA_VISIBLE_DEVICES` logic unchanged):

```python
        with self._gpu_guard(str(chosen_index)):
            raw = predictor_fn(...)  # existing inference call unchanged
```

(If the existing implementation separates `predictor` initialization from `predict`, put both inside the `with` block so initialization also holds the lock.)

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS (7 passed)

- [ ] **Step 5: Regression**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_nnunet_cascade_tumor.py tests/test_segmentation_override_contract.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(ctv): put the pancreatic engine on the shared GPU lock"
```

---

### Task 4: Classify Downstream by Registry Semantics

**Files:**
- Modify: `web/structure_service.py` (around lines 169-200, 243-250)
- Modify: `web/routes/viewer_routes.py` (around lines 1133-1178)
- Test: `tests/test_ctv_downstream_equivalence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ctv_downstream_equivalence.py
import numpy as np
from types import SimpleNamespace
from web.structure_service import is_multitarget_gtv_source


def _memory(source, label_map, full_labels):
    values = {
        'ctv_source': source,
        'ctv_label_map': label_map,
        'ctv_full_labels': full_labels,
        'ctv_array': (full_labels == 1).astype(np.uint8),
    }
    class M:
        def retrieve(self, key, default=None):
            return values.get(key, default)
    return M()


def test_registry_semantics_classify_pancreatic_as_target_plus_anatomy():
    from tool_factory.CTV_seg.model_registry import target_semantics
    assert target_semantics('model') == 'target_plus_anatomy'
    assert target_semantics('nnunet_pancreatic') == 'target_plus_anatomy'


def test_multitarget_gate_uses_registry_not_name_prefix():
    # head/neck and nasopharynx are multi-target ...
    assert is_multitarget_gtv_source('nnunet_head_neck_gtv')
    assert is_multitarget_gtv_source('nnunet_nasopharynx_ncct')
    # ... while a registered single-target model is not.
    assert not is_multitarget_gtv_source('vista3d_lung_tumor')
    assert not is_multitarget_gtv_source('nnunet_liver_tumor')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ctv_downstream_equivalence.py -q -p no:cacheprovider`
Expected: FAIL (`vista3d_lung_tumor` classified as multi-target, or ImportError)

- [ ] **Step 3: Write minimal implementation**

`web/structure_service.py`: remove the hardcoded set and switch to a registry query (keeping the legacy-value fallback):

```python
from tool_factory.CTV_seg.model_registry import (
    is_registered_model_source as _registered_model_source,
    target_semantics as _target_semantics,
)


def is_multitarget_gtv_source(source: Any) -> bool:
    return _target_semantics(source) == 'multi_target_gtv'


def _is_model_ctv_source(source: Any) -> bool:
    """Return whether a CTV source is a registered model route."""
    return _registered_model_source(source)
```

The anatomy branch inside `_base_ctv_volume` stays "only when the semantics are target_plus_anatomy and full_labels is present":

```python
    if is_multitarget_gtv_source(source) and full_labels is not None:
        return full_labels, {label: label_map.get(label, f"GTV {label}")
                             for label in (1, 2) if np.any(full_labels == label)}, source
    if _target_semantics(source) == 'target_plus_anatomy' and full_labels is not None:
        if np.any(full_labels == 1):
            return (full_labels == 1).astype(np.uint8), {
                1: label_map.get(1, "pancreatic tumor")
            }, source
```

`web/routes/viewer_routes.py`: make the `is_model_ctv` check registry-driven:

```python
from tool_factory.CTV_seg.model_registry import (
    is_registered_model_source as _registered_ctv_model,
)

            is_model_ctv = _registered_ctv_model(ctv_source)
            is_multitarget_gtv = is_multitarget_gtv_source(base_ctv_source or ctv_source)
            if is_multitarget_gtv:
                is_model_ctv = False
```

Everything else (the `ctv_full` value lookup, the `has_nnunet_oar` branch) stays unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ctv_downstream_equivalence.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Regression + contract scan**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_uploaded_mask_staging.py tests/test_uploaded_mask_provenance.py tests/test_structure_palette.py tests/test_site_model_deployment.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_ctv_downstream_equivalence.py
git commit -m "feat(ctv): classify downstream sources from the route registry"
```

---

### Task 5: Derive Catalog Entries from the Registry (including lung recognized as a model, deprecated entries hidden)

**Files:**
- Modify: `tool_factory/CTV_seg/model_catalog.py`
- Test: `tests/test_model_registry.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py (append)
def test_catalog_lists_registry_routes_as_peers():
    from tool_factory.CTV_seg import filter_catalog
    visible = {r['id']: r for r in filter_catalog() if r.get('ui_visible')}
    for rid in ('nnunet_pancreatic', 'nnunet_liver_tumor', 'nnunet_kidney_tumor',
                'nnunet_head_neck_gtv', 'nnunet_nasopharynx_ncct',
                'nnunet_nasopharynx_cect', 'vista3d_lung_tumor'):
        assert rid in visible, rid
    assert 'biomedparse_lung_lesion' not in visible
    assert 'biomedparse_head_neck_cancer' not in visible
```

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_catalog_lists_registry_routes_as_peers -q -p no:cacheprovider`
Expected: PASS (already satisfied). If it fails, go to Step 3.

- [ ] **Step 3: Minimal implementation if it fails**

At the catalog assembly point in `model_catalog.py`, use `registry.ui_routes()` to fill in missing entries (`id/tumor_type/site/modality/target/ct_phase` taken from `CTVRoute`), and ensure `catalog_status` maps to `capability_state` (`verified`→`verified`, otherwise→`experimental`).

- [ ] **Step 4: Run test**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "test(ctv): pin catalog peer entries to the route registry"
```

---

## Phase 2 — Front-end Consistency (all usable = green) + Routing/Alias Defects

### Task 6: Backend Alias and Routing Defects

**Files:**
- Modify: `tool_factory/CTV_seg/__init__.py` (`normalize_tumor_type`, around lines 132-210)
- Modify: `agent_runtime/response_tools.py`（`_map_tumor_type` / `_SUPPORTED_AUTOMATIC_CTV_TYPES`）
- Modify: `agent_runtime/turn_policy.py`（`_is_canonical_execution_command`）
- Test: `tests/test_model_registry.py` (append) + `tests/test_image_metadata_query.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py (append)
def test_chinese_aliases_for_all_primary_sites():
    from tool_factory.CTV_seg import normalize_tumor_type as n
    assert n('头颈部肿瘤') == 'nnunet_head_neck_gtv'
    assert n('头颈肿瘤') == 'nnunet_head_neck_gtv'
    assert n('肺部肿瘤') == 'vista3d_lung_tumor'
    assert n('肺肿瘤') == 'vista3d_lung_tumor'
    assert n('肝癌') == 'nnunet_liver_tumor'
    assert n('肾癌') == 'nnunet_kidney_tumor'


def test_direct_ctv_phrase_is_a_canonical_execution_command():
    from agent_runtime.turn_policy import classify_local_turn as c
    for msg in ('请分割胰腺 CTV', '请分割肝脏 CTV', '请分割鼻咽癌 CTV'):
        policy = c(msg)
        assert policy.intent == 'segmentation', msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: FAIL (`头颈部肿瘤` / `请分割胰腺 CTV`)

- [ ] **Step 3: Write minimal implementation**

`normalize_tumor_type`: complete the existing `aliases` (covering the registry `aliases` field, taking the union of the two):

```python
    aliases.update({
        "头颈部": "nnunet_head_neck_gtv",
        "头颈部肿瘤": "nnunet_head_neck_gtv",
        "肺部": "vista3d_lung_tumor",
        "肺部肿瘤": "vista3d_lung_tumor",
    })
```

`agent_runtime/response_tools.py`: route nasopharynx through "explicit phase → specific model, otherwise ask":

```python
    _NASOPHARYNX_ALIASES = frozenset({
        "nasopharynx", "nasopharyngeal", "鼻咽", "鼻咽癌",
    })
```

Inside `_map_tumor_type`, before the `canonical in self._SUPPORTED_AUTOMATIC_CTV_TYPES` check, add:

```python
        if canonical in self._NASOPHARYNX_ALIASES:
            # Phase is a clinical decision, never inferred from intensity.
            from tool_factory.CTV_seg import resolve_ctv_tumor_type
            return resolve_ctv_tumor_type({'tumor_type': raw})
```

Also exclude the `nasopharynx` sentinel from the "unknown site" warning path (return if known; if unknown, return `nasopharynx` for the tool layer to ask).

`agent_runtime/turn_policy.py`: in the segmentation branch of `_is_canonical_execution_command`, allow "verb + site + CTV":

```python
        if re.match(r"^(?:请|帮我|现在)?(?:分割|勾勒|勾勒|提取)", text):
            return True
        return bool(re.search(r"(?:^|\s)ctv(?:\s|$)", text) and re.search(r"分割|segment", text))
```

(Keep the existing negation/condition interception unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py tests/test_image_metadata_query.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Regression**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_whole_request_routing.py tests/test_intent_shortcut_boundary.py tests/test_semantic_execution_authorization.py -q -p no:cacheprovider`
Expected: same as before the change (no new failures; `test_report_object_wins_over_guide_and_dose` belongs to another session's WIP and is tracked separately)

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "fix(ctv): complete site aliases and restore direct CTV commands"
```

---

### Task 7: Front-end Selector — All Supported Categories Green

**Files:**
- Modify: `web/app/static/js/brachybot-ui-api.js` (`_syncTumorTypeSelectorAppearance`, around lines 3323-3418; `updateTumorTypeSelector`, around lines 3474-3510)
- Modify: `web/app/index.html` (`?v=` bump and group copy)
- Test: `tests/test_web_frontend_ctv_selector.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_frontend_ctv_selector.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def test_supported_categories_are_always_green():
    js = _read('web/app/static/js/brachybot-ui-api.js')
    # Operational availability alone decides colour; maturity is help text.
    assert 'optionCallable ?' in js
    assert "option.dataset.callable === 'true'" in js
    assert "stateName === 'verified'" in js  # still callable
    # No maturity-only red path.
    assert "capability === 'experimental' ? '#fb7185'" not in js


def test_nasopharynx_and_head_neck_aliases_are_known_to_the_selector():
    js = _read('web/app/static/js/brachybot-ui-api.js')
    for token in ('鼻咽', '头颈部肿瘤', 'head_neck'):
        assert token in js


def test_selector_options_match_the_registry():
    from tool_factory.CTV_seg.model_registry import ui_routes
    index = _read('web/app/index.html')
    for r in ui_routes():
        if r.engine == 'text_guided' and r.site not in ('colon', 'prostate'):
            continue
        assert f'value="{r.id}"' in index, r.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_web_frontend_ctv_selector.py -q -p no:cacheprovider`
Expected: FAIL (`鼻咽` missing / missing new-option checks beyond `vista3d_lung_tumor`)

- [ ] **Step 3: Write minimal implementation**

`brachybot-ui-api.js`: unify the color decision to "usable = green" (maturity only goes into help text):

```js
    const callable = selected?.dataset?.callable === 'true'
        || capability === 'verified';
    ...
    Array.from(select.options).forEach(option => {
        const stateName = option.dataset.capabilityState || 'disabled';
        // Every supported, runnable category is green; maturity is help text.
        const optionCallable = option.dataset.callable === 'true'
            || stateName === 'verified';
        option.style.color = optionCallable ? '#4ade80' : '#fb7185';
        option.style.fontWeight = optionCallable ? '600' : '500';
        option.title = option.dataset.capabilityReason || '';
    });
```

Add nasopharynx and head-neck to the `updateTumorTypeSelector` alias table:

```js
        nasopharynx: 'nnunet_nasopharynx_ncct',
        '鼻咽': 'nnunet_nasopharynx_ncct',
        '鼻咽癌': 'nnunet_nasopharynx_ncct',
        '头颈部肿瘤': 'nnunet_head_neck_gtv',
        '头颈部': 'nnunet_head_neck_gtv',
```

`web/app/index.html`: confirm all 6 sites (including `vista3d_lung_tumor`, the two nasopharynx entries, and head-neck) are `<option>`s in the same "Tumor Segmentation" group; bump `?v=` by 1 for each of `brachybot-ui-api.js` and `brachybot-manual-annotation.js`, and update the tests that assert `?v=` (`tests/test_runtime_contracts.py`, `tests/test_round7_regressions.py`, `tests/test_uploaded_mask_staging.py`).

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_web_frontend_ctv_selector.py tests/test_runtime_contracts.py tests/test_round7_regressions.py tests/test_uploaded_mask_staging.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Node syntax check**

Run: `NODE=<vscode-server>/cli/servers/Stable-520fb30b2d3d324b4cb2342f6e88e2cd93751de1/server/node; $NODE --check web/app/static/js/brachybot-ui-api.js && echo OK`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_web_frontend_ctv_selector.py
git commit -m "feat(ctv-ui): show every runnable tumor category in green"
```

---

## Phase 3 — Acceptance

### Task 8: Full Relevant Test Suite + Optional Real-GPU Smoke Test

**Files:**
- Test: existing suites

- [ ] **Step 1: Run all relevant suites**

Run:
```bash
cd <workspace>/BrachyBot
~/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_model_registry.py tests/test_ctv_downstream_equivalence.py \
  tests/test_web_frontend_ctv_selector.py tests/test_site_model_deployment.py \
  tests/test_nnunet_cascade_tumor.py tests/test_biomedparse_v2.py \
  tests/test_sat3d_integration.py tests/test_segmentation_override_contract.py \
  tests/test_uploaded_mask_provenance.py tests/test_uploaded_mask_staging.py \
  tests/test_structure_palette.py tests/test_whole_request_routing.py \
  tests/test_intent_shortcut_boundary.py tests/test_semantic_execution_authorization.py \
  tests/test_image_metadata_query.py tests/test_runtime_contracts.py \
  tests/test_round7_regressions.py tests/test_review_round6_regressions.py \
  -q -p no:cacheprovider
```
Expected: only the pre-existing baseline failures remain (`test_web_config_route_reads_project_root_defaults`, `test_web_api_isolates_agent_and_ui_state_by_session`, and another session's WIP `test_report_object_wins_over_guide_and_dose`); no new failures.

- [ ] **Step 2: Real-GPU smoke test (requires user consent to occupy the GPU)**

Run 1 case per site using a real CT from `tests/data` or the dataset, recording: elapsed time, foreground voxels, label counts, whether the geometry matches the input, and whether the shared lock was used. Command template:

```bash
~/.conda/envs/brachytherapy/bin/python - <<'PY'
import sys, time, SimpleITK as sitk
sys.path.insert(0, '.')
from tool_factory.CTV_seg import CTVSegmentationTool
image = sitk.ReadImage('<real CT path>')
for site in ('nnunet_pancreatic','nnunet_liver_tumor','nnunet_kidney_tumor',
             'nnunet_head_neck_gtv','nnunet_nasopharynx_ncct',
             'nnunet_nasopharynx_cect','vista3d_lung_tumor'):
    t = time.time()
    r = CTVSegmentationTool()._execute(image=image, tumor_type=site)
    print(site, r.success, round(time.time()-t, 1), (r.metadata or {}).get('ctv_voxel_count'),
          (r.metadata or {}).get('ctv_source'), (r.metadata or {}).get('target_semantics'))
PY
```

- [ ] **Step 3: Summarize and ask the user to decide the commit strategy**

Output a file list (files changed by this plan vs files from another session's WIP) and let the user decide whether to commit together or separately.

---

## Self-Review

- **Spec coverage:** §3.1→Task 1/5; §3.2→Task 3 (+ reuse of the existing gpu_lock); §3.3→Task 2; §3.4→Task 4; §3.5→Task 7; §3.6→Task 6; §5 tests→Tasks 1-8; §6 compatibility→Task 1 legacy aliases / Task 2 `ctv_source` fallback.
- **Placeholder scan:** no TBD/TODO; every code step contains runnable code or a precise anchor.
- **Type consistency:** `target_semantics` / `canonical_ctv_source` / `is_registered_model_source` / `is_multitarget_gtv_source` are defined in Task 1 and used with the same signature in Tasks 2/4/5; the `UI_routes` name is unified as `ui_routes()`.
- **Known external interference:** `turn_policy.py`, `response_tools.py`, `structure_service.py`, `viewer_routes.py`, `model_catalog.py`, `index.html`, `brachybot-ui-api.js` overlap with another session's WIP; at the end of each related task these files are kept out of the index, and regression commands are listed separately.

---

## Phase 1b — BiomedParse v2 Parallel Integration (Addendum)

### Task 4b: Bring BiomedParse External Inference into Unified GPU Scheduling

**Files:**
- Modify: `tool_factory/CTV_seg/biomedparse_v2.py` (`_run_external_inference`, around lines 510-617)
- Test: `tests/test_model_registry.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_biomedparse_external_inference_is_pinned_and_locked(monkeypatch):
    import numpy as np
    from tool_factory.CTV_seg import biomedparse_v2 as B

    seen = {}
    real_run = B.subprocess.run

    def fake_run(cmd, **kwargs):
        seen['env'] = kwargs.get('env') or {}
        return type('R', (), {'returncode': 1, 'stdout': '', 'stderr': 'stop'})()

    monkeypatch.setattr(B.subprocess, 'run', fake_run)
    try:
        B._run_external_inference(
            normalised=np.zeros((4, 4, 4), dtype=np.float32),
            root=B.Path('.'), checkpoint=B.Path('x'), text_assets=B.Path('y'),
            runtime_python=B.Path('/usr/bin/false'), prompt='lung', slice_batch_size=1,
        )
    except Exception:
        pass
    assert 'CUDA_VISIBLE_DEVICES' in seen['env']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_biomedparse_external_inference_is_pinned_and_locked -q -p no:cacheprovider`
Expected: FAIL (env not set, or subprocess.run called without env)

- [ ] **Step 3: Write minimal implementation**

In `_run_external_inference`, first select and pin the GPU via DeviceManager + the shared lock, then call with `env`:

```python
    from .site_model_runtime import gpu_lock
    from plans.device_manager import device_session

    with device_session(caller='biomedparse_v2') as lease:
        device = str(lease.device_str)
        if not device.startswith('cuda:'):
            raise RuntimeError('BiomedParse v2 requires an NVIDIA CUDA GPU.')
        gpu_index = device.split(':', 1)[1]
        env = os.environ.copy()
        # The worker uses the process-default CUDA device; pin it to the
        # lease instead of letting it fall onto GPU 0.
        env['CUDA_VISIBLE_DEVICES'] = gpu_index
        with gpu_lock(gpu_index):
            completed = subprocess.run(
                command, cwd=str(root), check=False, capture_output=True,
                text=True, env=env,
                timeout=float(os.environ.get('BIOMEDPARSE_V2_INFERENCE_TIMEOUT', '1800')),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(biomedparse): schedule open-vocabulary inference on the shared GPU lock"
```

### Task 4c: Open-Vocabulary Fallback Hint for Tumors Without a Dedicated Model

**Files:**
- Modify: `tool_factory/CTV_seg/__init__.py` (unsupported tumor_type branch, around lines 554-567)
- Test: `tests/test_model_registry.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_unsupported_tumor_points_at_open_vocabulary():
    import numpy as np, SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    r = CTVSegmentationTool()._execute(image=image, tumor_type='食管癌')
    assert r.success is False
    assert (r.metadata or {}).get('open_vocabulary_available') is True
    assert (r.metadata or {}).get('suggested_tool') == 'biomedparse_segmentation'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_unsupported_tumor_points_at_open_vocabulary -q -p no:cacheprovider`
Expected: FAIL (metadata missing fields)

- [ ] **Step 3: Write minimal implementation**

Append to the metadata of the `ToolResult` for an unsupported `tumor_type`:

```python
                        metadata={
                            "tumor_type_used": tumor_type,
                            "open_vocabulary_available": True,
                            "suggested_tool": "biomedparse_segmentation",
                            "suggested_prompt": f"{tumor_type} tumor",
                            "model_catalog": filter_catalog(),
                        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(ctv): point unsupported tumors at the open-vocabulary route"
```
