"""Structured artifact tree against real leaf handlers, no patient data."""
import pytest

from test_planning_distance_annotations_browser import page,browser,install,JS,ROOT
from test_viewers_toolbar_browser import function


@pytest.fixture
def organized(page):
    volume=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content='\n'.join(function(volume,name) for name in ['renderArtifactTreeItem','_dataTreeGroupObjectIds','_dataTreeExportGroups','exportDataTreeGroup']))
    page.add_script_tag(path=str(JS/'brachybot-artifact-tree.js'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-panels-viewers.css'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-theme-layout.css'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-report-controls.css'))
    page.evaluate('document.documentElement.dataset.theme="dark"')
    page.add_script_tag(content='''
        window._dtText=(zh,en)=>window._i18nLang==='zh'?zh:en;
        window._viewerDataSessionId=()=>activeSessionId;
        window.renderDataTree=()=>{
            reconcileViewerAnnotationNodes();
            const host=document.getElementById('dataTreeBody');
            host.innerHTML=renderStructuredArtifactTree(dataTreeState.annotations,dataTreeState.exportArtifacts||[],renderTreeItem,renderArtifactTreeItem);
            bindStructuredArtifactTree(host);
        };
        window.hideContextMenu=()=>document.getElementById('ctxMenu')?.remove();
        window._runDataTreeAction=async x=>x;
        window.exportDialogs=[];window.openSessionExportDialog=async opts=>exportDialogs.push(opts);
        window.handleTreeItemClick=(id,e)=>{window.clickedArtifact=id};
        window.handleTreeItemRightClick=(id,e)=>{e.preventDefault();window.rightClickedArtifact=id};
    ''')
    install(page)
    page.evaluate('''() => {
        const item=(id,type,label,meta={})=>({id:'artifact_'+encodeURIComponent(id),objectId:id,dataType:type,label,
            artifactMetadata:meta,viewMetadata:meta.view_metadata||{},loaded:true,color:'#38bdf8',visible:true,opacity:1,
            planningId:meta.planning_id||null});
        dataTreeState.exportArtifacts=[item('report:data','report_data','Report data'),
            item('figure:1a.png','report_figure','Reference-direction front view',{planning_id:'plan',view_metadata:{figure_number:1,subfigure:'a',sort_order:1}}),
            item('figure:1b.png','report_figure','Translucent tumour',{planning_id:'plan',view_metadata:{figure_number:1,subfigure:'b',sort_order:2}}),
            item('screenshot:raw.png','screenshot','chat_screenshot_a',{artifact_family:'chat_capture',request_id:'request-1',capture_source_id:'capture1',capture_variant:'original',target:'viewer-3d',created_at:100}),
            item('screenshot:marked.png','screenshot','annotated_chat_screenshot_a_h',{artifact_family:'chat_capture',request_id:'request-1',capture_source_id:'capture1',capture_variant:'annotated',target:'viewer-3d',created_at:100}),
            item('screenshot:older.png','screenshot','chat_screenshot_b',{artifact_family:'chat_capture',request_id:'request-2',capture_source_id:'capture2',capture_variant:'original',target:'data-tree',created_at:50}),
            item('screenshot:unknown.png','screenshot','unclassified_file')];
        state.annotations.push({id:'line1',type:'line',axis:'axial',x1:0,x2:10,y1:0,y2:0,spacingX:1,spacingY:1,label:'Line · Axial · 10 mm',visible:true});
        renderDataTree();
    }''')
    return page


def branch(page,id):
    return page.locator(f'[data-artifact-group-id="artifacts:{id}"]')


def test_every_leaf_has_one_meaningful_family_and_no_duplicate_dom_identity(organized):
    page=organized
    assert branch(page,'automatic').count()==1
    assert branch(page,'manual').count()==1
    assert branch(page,'report').count()==1
    assert branch(page,'screenshots').count()==1
    assert branch(page,'other').count()==1
    ids=page.locator('#dataTreeBody .tree-item').evaluate_all('nodes=>nodes.map(n=>n.dataset.objectId)')
    assert len(ids)==len(set(ids))==12
    assert branch(page,'screenshots:request-1').locator('.tree-item').count()==2
    assert branch(page,'screenshots:request-1:capture1').locator('.tree-item').count()==2
    assert 'Annotated image' in branch(page,'screenshots:request-1').text_content()
    assert 'Original capture' in branch(page,'screenshots:request-1').text_content()


def test_search_opens_only_matching_attachment_branches_and_preserves_ids(organized):
    page=organized;page.locator('.artifact-tree-search input').fill('marked.png')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==1
    assert branch(page,'screenshots:request-1').evaluate('e=>e.open')
    page.locator('.artifact-tree-leaf:not([hidden]) .tree-item').click()
    assert page.evaluate('clickedArtifact')=='artifact_screenshot%3Amarked.png'
    assert branch(page,'report').evaluate('e=>e.hidden')
    assert page.locator('.artifact-tree-search-result').inner_text()=='1 matches'
    page.locator('.artifact-tree-search input').fill('')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==12


def test_search_finds_generated_needle_seed_or_manual_measurement(organized):
    page=organized;page.locator('.artifact-tree-search input').fill('seed_1_2')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==1
    page.locator('.artifact-tree-search input').fill('Axial')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==1
    assert 'Line' in page.locator('.artifact-tree-leaf:not([hidden])').inner_text()


def test_group_export_is_exact_descendants_not_whole_session(organized):
    page=organized
    page.evaluate('exportDataTreeGroup("artifacts:screenshots:request-1")')
    proposal=page.evaluate('exportDialogs[0]')
    assert set(proposal['objectIds'])=={'screenshot:raw.png','screenshot:marked.png'}
    assert proposal['sessionId']=='case' and proposal['groupIds']==[]


def test_group_open_state_and_search_survive_workspace_projection(organized):
    page=organized
    branch(page,'screenshots').locator(':scope > summary').click()
    page.wait_for_timeout(20)
    saved=page.evaluate('JSON.parse(JSON.stringify(dataTreeState.artifactBrowser))')
    page.evaluate('renderDataTree()')
    assert branch(page,'screenshots').evaluate('e=>e.open')
    page.evaluate('x=>dataTreeState.artifactBrowser=x',saved)
    page.evaluate('renderDataTree()')
    assert branch(page,'screenshots').evaluate('e=>e.open')


def test_global_language_relabels_categories_pairs_and_search(organized):
    page=organized
    page.evaluate('window._i18nLang="zh";window.dispatchEvent(new CustomEvent("i18nchange"))')
    assert '对话截图' in branch(page,'screenshots').text_content()
    assert '原始截图' in branch(page,'screenshots:request-1').text_content()
    assert page.locator('.artifact-tree-search input').get_attribute('placeholder').startswith('搜索')


def test_annotation_group_menu_never_advertises_inapplicable_2d_or_destructive_delete(organized):
    page=organized
    page.evaluate('showStructuredArtifactContextMenu(20,20,"artifacts:automatic")')
    text=page.locator('#ctxMenu').inner_text()
    assert 'Hide group annotations' in text and 'Delete' not in text and '2D' not in text
    page.locator('#ctxMenu button').filter(has_text='Hide group annotations').click()
    assert page.evaluate('state.annotations.filter(r=>r.type==="planning_distance").every(r=>r.visible===false)')


def test_unknown_filenames_are_tooltips_not_an_unreadable_flat_label(organized):
    page=organized
    item=branch(page,'other').locator('.item-label')
    assert item.text_content()=='Saved image 1'
    assert 'unknown.png' in item.get_attribute('title')


def test_user_strings_cannot_inject_artifact_tree_or_context_menu(organized):
    page=organized
    page.evaluate('dataTreeState.exportArtifacts[1].label="<img src=x onerror=alert(1)>";renderDataTree()')
    assert page.locator('#dataTreeBody img').count()==0
    assert '<img' in branch(page,'report').text_content()


def test_custom_alias_and_source_filename_both_remain_searchable(organized):
    page=organized
    page.evaluate('dataTreeState.exportArtifacts.find(r=>r.objectId==="screenshot:unknown.png").customLabel="Useful anatomy view";renderDataTree()')
    page.locator('.artifact-tree-search input').fill('Useful anatomy')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==1
    assert 'Useful anatomy view' in page.locator('.artifact-tree-leaf:not([hidden])').inner_text()
    page.locator('.artifact-tree-search input').fill('unknown.png')
    assert page.locator('.artifact-tree-leaf:not([hidden])').count()==1


@pytest.mark.parametrize('theme', ['dark','light'])
def test_structured_browser_inherits_global_theme_tokens(organized,theme):
    page=organized
    page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
    colours=page.evaluate('''() => ({label:getComputedStyle(document.querySelector('.artifact-tree-heading')).color,
        root:getComputedStyle(document.documentElement).getPropertyValue('--text').trim(),
        input:getComputedStyle(document.querySelector('.artifact-tree-search input')).color})''')
    expected=page.evaluate('hex=>{const e=document.createElement("span");e.style.color=hex;document.body.append(e);const c=getComputedStyle(e).color;e.remove();return c;}',colours['root'])
    assert colours['label']==colours['input']==expected
