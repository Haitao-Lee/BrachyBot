from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def test_supported_categories_are_always_green():
    js = _read('web/app/static/js/brachybot-ui-api.js')
    # Operational availability alone decides colour; the server-rendered
    # categories are all supported, so they bootstrap green until the async
    # capability probe can downgrade a missing model to red.
    assert "option.dataset.callable === 'true'" in js
    assert "stateName === 'loading'" in js
    assert "capability === 'loading'" in js
    assert "optionCallable ? '#4ade80' : '#fb7185'" in js


def test_nasopharynx_and_head_neck_aliases_are_known_to_the_selector():
    js = _read('web/app/static/js/brachybot-ui-api.js')
    for token in ('鼻咽', '头颈部肿瘤', 'head_neck', 'nnunet_nasopharynx_ncct'):
        assert token in js


def test_selector_options_match_the_registry():
    from tool_factory.CTV_seg.model_registry import ui_routes
    index = _read('web/app/index.html')
    for r in ui_routes():
        assert f'value="{r.id}"' in index, r.id
