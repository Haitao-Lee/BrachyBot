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
    ui_visible: bool = True
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
    'biomedparse_segmentation': CTVRoute(
        'biomedparse_segmentation', 'open_vocabulary', '开放词汇（任意部位/肿瘤）', 'Open vocabulary (any site)',
        'text_guided', target_semantics='candidate_mask',
        family='biomedparse', family_key='open_vocabulary',
        catalog_status='experimental', requires_review=True, ui_visible=False,
        aliases=('开放词汇', 'open vocabulary', 'open-vocabulary')),
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
    return [r for r in CTV_ROUTES.values() if r.ui_visible]


def aliases() -> Dict[str, str]:
    """canonical alias -> route id (legacy spellings included)."""
    table = {}
    for r in CTV_ROUTES.values():
        table[r.id] = r.id
        for alias in r.aliases:
            table[str(alias).casefold()] = r.id
    return table
