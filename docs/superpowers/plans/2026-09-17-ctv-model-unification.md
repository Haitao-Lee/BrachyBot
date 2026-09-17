# CTV 肿瘤分割统一门类 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让胰腺/肝/肾/头颈/鼻咽(平扫、增强)/肺六个肿瘤分割模型成为同一门类的对等条目，统一注册、统一 GPU 调度、统一输出契约与下游语义、统一前端体验（可用即绿）。

**Architecture:** 新增 `model_registry.py` 作为管理/语义的唯一事实源（引用现有三套执行 spec，不重写引擎）；把共享调度抽到执行边界（胰腺也纳入跨进程 `gpu_lock`）；`CTVSegmentationTool` 归一输出并统一 `ctv_source` 为路由 id；下游 `structure_service`/`viewer_routes` 改为按注册表 `target_semantics` 分类（旧快照走后缀别名回退）；前端选择器/可用性由注册表驱动，所有可用类别绿色。

**Tech Stack:** Python 3.12（`~/.conda/envs/brachytherapy/bin/python`）、pytest、Flask、SimpleITK、nnUNet v2、原生 JS（`web/app/static/js`）、Node（语法检查，路径见下）。

**关键约定**
- 路由 id 保持不变（`nnunet_pancreatic` / `nnunet_liver_tumor` / `nnunet_kidney_tumor` / `nnunet_head_neck_gtv` / `nnunet_nasopharynx_ncct` / `nnunet_nasopharynx_cect` / `vista3d_lung_tumor`）。
- 端到端测试命令：`~/.conda/envs/brachytherapy/bin/python -m pytest <path> -q -p no:cacheprovider`
- Node：`<vscode-server>/cli/servers/Stable-520fb30b2d3d324b4cb2342f6e88e2cd93751de1/server/node`
- **提交纪律**：本工作区有另一会话未提交改动。仅对"纯属本计划"的文件执行 `git add`（新模块 + 新测试）。共享文件（`__init__.py`、`structure_service.py`、`viewer_routes.py`、`planning_routes.py`、`response_tools.py`、`turn_policy.py`、`index.html`、`brachybot-ui-api.js`）在本计划中**不改 git 索引**，完成后再统一决定提交。

---

## File Structure

- Create: `BrachyBot/tool_factory/CTV_seg/model_registry.py` — 路由表与派生助手（管理/语义唯一事实源）。
- Create: `BrachyBot/tests/test_model_registry.py` — 注册表契约测试。
- Create: `BrachyBot/tests/test_ctv_downstream_equivalence.py` — 下游等价测试。
- Modify: `BrachyBot/tool_factory/CTV_seg/__init__.py` — 由注册表派生别名/工具表；统一 `ctv_source`；统一 `label_stats`。
- Modify: `BrachyBot/tool_factory/CTV_seg/pancreatic_tumor_nnunet.py` — 纳入共享 `gpu_lock`。
- Modify: `BrachyBot/web/structure_service.py` — 按注册表语义分类。
- Modify: `BrachyBot/web/routes/viewer_routes.py` — 按注册表语义分类。
- Modify: `BrachyBot/agent_runtime/response_tools.py` — 鼻咽哨兵处理。
- Modify: `BrachyBot/agent_runtime/turn_policy.py` — `<部位> CTV` 直执行。
- Modify: `BrachyBot/web/app/index.html` — 选择器选项与分类文案（由注册表校对）。
- Modify: `BrachyBot/web/app/static/js/brachybot-ui-api.js` — 全绿可用性、别名、相位。
- Tests: `BrachyBot/tests/test_site_model_deployment.py`、`tests/test_nnunet_cascade_tumor.py`、`tests/test_web_frontend_ctv_selector.py`（新建）。

---

## Phase 1 — 后端注册表 / 执行边界 / 输出契约 / 下游语义

### Task 1: 注册表模块

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
Expected: PASS（5 passed）

- [ ] **Step 5: Commit (only our new files)**

```bash
cd <workspace>/BrachyBot
git add tool_factory/CTV_seg/model_registry.py tests/test_model_registry.py
git commit -m "feat(ctv): add unified tumor-segmentation route registry"
```

---

### Task 2: 统一 `ctv_source` 与补全 `label_stats`

**Files:**
- Modify: `tool_factory/CTV_seg/__init__.py`（`meta` 构造段，约 824-845 行）
- Test: `tests/test_model_registry.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py 追加
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

> 注：`_resolve_tool` 是 Task 2 新增的内部间接层，便于在包裹层测试中注入假引擎（见 Step 3）。

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py::test_metadata_contract_is_identical_across_engines -q -p no:cacheprovider`
Expected: FAIL（`KeyError: 'target_semantics'` 或 `_resolve_tool` 不存在）

- [ ] **Step 3: Write minimal implementation**

在 `__init__.py` 顶部 import 注册表：

```python
from .model_registry import (
    canonical_ctv_source, target_semantics, aliases as registry_aliases,
)
```

在 `CTVSegmentationTool` 内新增间接层（供测试注入与统一调度复用）：

```python
    def _resolve_tool(self, tumor_type: str):
        return TOOL_REGISTRY[tumor_type]()
```

把 `tool = TOOL_REGISTRY[tumor_type]()` 改为 `tool = self._resolve_tool(tumor_type)`。

在 `meta` 字典（约 824 行）中，将 `ctv_source` 与新增字段改为：

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

并在 `meta` 之后补统一的 `label_stats`（胰腺已自带；其余为空时由 `full_label_array`/`ctv_array` 现算）：

```python
        if not from_label_path and not meta["label_stats"]:
            stats_source = res_meta.get("full_label_array")
            if stats_source is None:
                stats_source = ctv_array
            meta["label_stats"] = _label_stats_from_array(
                stats_source, meta["label_map"], ctv_mask.GetSpacing(),
            )
```

在 `__init__.py` 模块级新增（放在 `_normalize_label_stats` 附近）：

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
Expected: PASS（6 passed）

- [ ] **Step 5: 回归**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_site_model_deployment.py tests/test_nnunet_cascade_tumor.py tests/test_uploaded_mask_provenance.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(ctv): unify ctv_source and label_stats across engines"
```
（`__init__.py` 与另一会话的 WIP 共享，暂不入索引。）

---

### Task 3: 胰腺纳入统一 GPU 调度

**Files:**
- Modify: `tool_factory/CTV_seg/pancreatic_tumor_nnunet.py`（`_run_nnunet_inference`，约 449-570 行）
- Test: `tests/test_model_registry.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py 追加
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

在 `pancreatic_tumor_nnunet.py` 顶部 import：

```python
from contextlib import contextmanager
```

在类内新增（放在 `_run_nnunet_inference` 之前）：

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

在 `_run_nnunet_inference` 内、真正把张量送到 GPU 之前用 `_gpu_guard` 包住推理调用（保持原有 DeviceManager 选择与 `CUDA_VISIBLE_DEVICES` 逻辑不变）：

```python
        with self._gpu_guard(str(chosen_index)):
            raw = predictor_fn(...)  # 现有推理调用保持不变
```

（若现有实现把 `predictor` 初始化与 `predict` 分开，两层都放进 `with` 内，确保初始化也持锁。）

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py -q -p no:cacheprovider`
Expected: PASS（7 passed）

- [ ] **Step 5: 回归**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_nnunet_cascade_tumor.py tests/test_segmentation_override_contract.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "feat(ctv): put the pancreatic engine on the shared GPU lock"
```

---

### Task 4: 下游按注册表语义分类

**Files:**
- Modify: `web/structure_service.py`（约 169-200、243-250 行）
- Modify: `web/routes/viewer_routes.py`（约 1133-1178 行）
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
Expected: FAIL（`vista3d_lung_tumor` 被判为 multi-target 或 ImportError）

- [ ] **Step 3: Write minimal implementation**

`web/structure_service.py`：删掉硬编码集合，改为注册表查询（保留旧值回退）：

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

`_base_ctv_volume` 内的解剖分支保持"仅当语义为 target_plus_anatomy 且有 full_labels 时"：

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

`web/routes/viewer_routes.py`：把 `is_model_ctv` 的判定改为注册表驱动：

```python
from tool_factory.CTV_seg.model_registry import (
    is_registered_model_source as _registered_ctv_model,
)

            is_model_ctv = _registered_ctv_model(ctv_source)
            is_multitarget_gtv = is_multitarget_gtv_source(base_ctv_source or ctv_source)
            if is_multitarget_gtv:
                is_model_ctv = False
```

其余（`ctv_full` 取值、`has_nnunet_oar` 分支）保持不变。

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ctv_downstream_equivalence.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 回归 + 契约扫描**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_uploaded_mask_staging.py tests/test_uploaded_mask_provenance.py tests/test_structure_palette.py tests/test_site_model_deployment.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_ctv_downstream_equivalence.py
git commit -m "feat(ctv): classify downstream sources from the route registry"
```

---

### Task 5: 目录条目由注册表派生（含肺被识别为模型、弃用项隐藏）

**Files:**
- Modify: `tool_factory/CTV_seg/model_catalog.py`
- Test: `tests/test_model_registry.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py 追加
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
Expected: PASS（当前已满足）。若失败，进入 Step 3。

- [ ] **Step 3: 若失败则最小实现**

在 `model_catalog.py` 的 catalog 组装处，用 `registry.ui_routes()` 补充缺失条目（`id/tumor_type/site/modality/target/ct_phase` 取自 `CTVRoute`），并确保 `catalog_status` 映射为 `capability_state`（`verified`→`verified`，其余→`experimental`）。

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

## Phase 2 — 前端一致（全部可用即绿）+ 路由/别名缺陷

### Task 6: 后端别名与路由缺陷

**Files:**
- Modify: `tool_factory/CTV_seg/__init__.py`（`normalize_tumor_type`，约 132-210 行）
- Modify: `agent_runtime/response_tools.py`（`_map_tumor_type` / `_SUPPORTED_AUTOMATIC_CTV_TYPES`）
- Modify: `agent_runtime/turn_policy.py`（`_is_canonical_execution_command`）
- Test: `tests/test_model_registry.py`（追加）+ `tests/test_image_metadata_query.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py 追加
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
Expected: FAIL（`头颈部肿瘤` / `请分割胰腺 CTV`）

- [ ] **Step 3: Write minimal implementation**

`normalize_tumor_type`：在现有 `aliases` 中补齐（覆盖注册表 `aliases` 字段，二者取并集）：

```python
    aliases.update({
        "头颈部": "nnunet_head_neck_gtv",
        "头颈部肿瘤": "nnunet_head_neck_gtv",
        "肺部": "vista3d_lung_tumor",
        "肺部肿瘤": "vista3d_lung_tumor",
    })
```

`agent_runtime/response_tools.py`：让鼻咽走"相位明确→具体模型，否则提问"：

```python
    _NASOPHARYNX_ALIASES = frozenset({
        "nasopharynx", "nasopharyngeal", "鼻咽", "鼻咽癌",
    })
```

在 `_map_tumor_type` 内 `canonical in self._SUPPORTED_AUTOMATIC_CTV_TYPES` 判定之前加入：

```python
        if canonical in self._NASOPHARYNX_ALIASES:
            # Phase is a clinical decision, never inferred from intensity.
            from tool_factory.CTV_seg import resolve_ctv_tumor_type
            return resolve_ctv_tumor_type({'tumor_type': raw})
```

并把 `nasopharynx` 哨兵从"未知站点"警告路径中排除（已知则返回，未知则返回 `nasopharynx` 供工具层提问）。

`agent_runtime/turn_policy.py`：在 `_is_canonical_execution_command` 的 segmentation 分支，允许"动词+部位+CTV"：

```python
        if re.match(r"^(?:请|帮我|现在)?(?:分割|勾勒|勾勒|提取)", text):
            return True
        return bool(re.search(r"(?:^|\s)ctv(?:\s|$)", text) and re.search(r"分割|segment", text))
```

（保持既有的否定/条件拦截不变。）

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_model_registry.py tests/test_image_metadata_query.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_whole_request_routing.py tests/test_intent_shortcut_boundary.py tests/test_semantic_execution_authorization.py -q -p no:cacheprovider`
Expected: 与改动前一致（不得新增失败；`test_report_object_wins_over_guide_and_dose` 属另一会话 WIP，单独跟踪）

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_model_registry.py
git commit -m "fix(ctv): complete site aliases and restore direct CTV commands"
```

---

### Task 7: 前端选择器——所有已支持类别绿色

**Files:**
- Modify: `web/app/static/js/brachybot-ui-api.js`（`_syncTumorTypeSelectorAppearance`，约 3323-3418 行；`updateTumorTypeSelector`，约 3474-3510 行）
- Modify: `web/app/index.html`（`?v=` bump 与分组文案）
- Test: `tests/test_web_frontend_ctv_selector.py`（新建）

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
Expected: FAIL（`鼻咽` 缺失 / 选项缺 `vista3d_lung_tumor` 之外的新项检查）

- [ ] **Step 3: Write minimal implementation**

`brachybot-ui-api.js`：把颜色判定统一为"可用即绿"（成熟度只进帮助文字）：

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

`updateTumorTypeSelector` 的别名表补鼻咽与头颈部：

```js
        nasopharynx: 'nnunet_nasopharynx_ncct',
        '鼻咽': 'nnunet_nasopharynx_ncct',
        '鼻咽癌': 'nnunet_nasopharynx_ncct',
        '头颈部肿瘤': 'nnunet_head_neck_gtv',
        '头颈部': 'nnunet_head_neck_gtv',
```

`web/app/index.html`：确认 6 站（含 `vista3d_lung_tumor`、两个鼻咽、头颈）都是同一"肿瘤分割"分组的 `<option>`；`brachybot-ui-api.js` 与 `brachybot-manual-annotation.js` 的 `?v=` 各 +1，并同步更新断言 `?v=` 的测试（`tests/test_runtime_contracts.py`、`tests/test_round7_regressions.py`、`tests/test_uploaded_mask_staging.py`）。

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_web_frontend_ctv_selector.py tests/test_runtime_contracts.py tests/test_round7_regressions.py tests/test_uploaded_mask_staging.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Node 语法检查**

Run: `NODE=<vscode-server>/cli/servers/Stable-520fb30b2d3d324b4cb2342f6e88e2cd93751de1/server/node; $NODE --check web/app/static/js/brachybot-ui-api.js && echo OK`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd <workspace>/BrachyBot
git add tests/test_web_frontend_ctv_selector.py
git commit -m "feat(ctv-ui): show every runnable tumor category in green"
```

---

## Phase 3 — 验收

### Task 8: 全量相关测试 + 可选真实 GPU 冒烟

**Files:**
- Test: 既有套件

- [ ] **Step 1: 相关套件全跑**

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
Expected: 仅剩既有基线失败（`test_web_config_route_reads_project_root_defaults`、`test_web_api_isolates_agent_and_ui_state_by_session`、另一会话 WIP 的 `test_report_object_wins_over_guide_and_dose`），无新增。

- [ ] **Step 2: 真实 GPU 冒烟（需用户同意占用 GPU）**

对每站用 `tests/data` 或数据集中的真实 CT 各跑 1 例，记录：耗时、前景体素、标签计数、几何是否与输入一致、是否经共享锁。命令模板：

```bash
~/.conda/envs/brachytherapy/bin/python - <<'PY'
import sys, time, SimpleITK as sitk
sys.path.insert(0, '.')
from tool_factory.CTV_seg import CTVSegmentationTool
image = sitk.ReadImage('<真实 CT 路径>')
for site in ('nnunet_pancreatic','nnunet_liver_tumor','nnunet_kidney_tumor',
             'nnunet_head_neck_gtv','nnunet_nasopharynx_ncct',
             'nnunet_nasopharynx_cect','vista3d_lung_tumor'):
    t = time.time()
    r = CTVSegmentationTool()._execute(image=image, tumor_type=site)
    print(site, r.success, round(time.time()-t, 1), (r.metadata or {}).get('ctv_voxel_count'),
          (r.metadata or {}).get('ctv_source'), (r.metadata or {}).get('target_semantics'))
PY
```

- [ ] **Step 3: 汇总并请用户决定提交策略**

输出一份文件清单（本计划改动的文件 vs 另一会话 WIP 的文件），由用户决定统一提交或分次提交。

---

## Self-Review

- **Spec coverage**：§3.1→Task1/5；§3.2→Task3（+现有 gpu_lock 复用）；§3.3→Task2；§3.4→Task4；§3.5→Task7；§3.6→Task6；§5 测试→Task1-8；§6 兼容→Task1 的 legacy 别名/Task2 的 `ctv_source` 回退。
- **Placeholder scan**：无 TBD/TODO；每个代码步骤含可执行代码或精确锚点。
- **Type consistency**：`target_semantics` / `canonical_ctv_source` / `is_registered_model_source` / `is_multitarget_gtv_source` 在 Task1 定义，Task2/4/5 使用同一签名；`UI_routes` 命名统一为 `ui_routes()`。
- **已知外部干扰**：`turn_policy.py`、`response_tools.py`、`structure_service.py`、`viewer_routes.py`、`model_catalog.py`、`index.html`、`brachybot-ui-api.js` 与另一会话 WIP 重叠；每个相关任务末尾都不把这些文件入索引，并单列回归命令。
