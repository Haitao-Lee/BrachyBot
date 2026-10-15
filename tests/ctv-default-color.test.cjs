const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2];
const baseline = process.argv.includes('--baseline');
const source = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-viewer-volume.js'), 'utf8');
function fn(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const ctx = vm.createContext({
  window: {}, console,
  ctvLabelColorLUT: {1:[255,48,76],2:[77,157,224],3:[255,48,76]},
  oarLabelColorLUT: {1:[77,157,224]}, labelColorLUT: {},
  ctvStructureCatalog: [],
  dataTreeState: {ct:{},ctv:{visible:true,opacity:0.7},skin:{},oar:{},dose:{},seeds:{},ctvLabels:{},organs:[]},
  state: {ctLoaded:true,maskLabels:{}},
  ctvLabelData: new Uint8Array([1,1,2,3]), oarLabelData:null,
  document:{getElementById:()=>({})},
  _deduplicatePlanningRows(){},reconcileDataTreeVisualNodes(){},hydrateDataTreeArtifactCatalog(){},
  getLabelVolumeCounts: array => { const m=new Map();for(const n of array||[])if(n)m.set(n,(m.get(n)||0)+1);return m; },
  escHtml:s=>s, _dtText:(a,b)=>b, renderTreeItem:()=>'', _disposeSceneMesh(){},
  _ctVoxelVolumeCm3:()=>0.001, _pendingStructurePresentation:()=>null,
  ensureDataTreeNodeMetadata:item=>item,
});
const constants=source.slice(source.indexOf('const ORGAN_COLORS ='),source.indexOf('function _normalizeStructureColor('));
const defaults=[...source.matchAll(/^const (?:STRUCTURE_PALETTE_VERSION|DEFAULT_\w+COLOR) = .*;$/gm)].map(x=>x[0]).join('\n');
vm.runInContext(defaults+'\n'+constants+'\n'+[
  '_normalizeStructureColor','_setStructureLutColor','syncStructureColorLUTsFromTree',
  '_structurePaletteColor','_rgbForStructureColor','isCTVTargetLabel','_ctvLabelPresentation','_setMeshMaterialColor',
].map(fn).join('\n'),ctx);
if(baseline){
  assert.equal(ctx._normalizeStructureColor(''),'#cccccc');
  assert.deepEqual(Array.from(ctx._ctvLabelPresentation(1).color),[204,204,204]);
  console.log('BASELINE REPRODUCED: missing saved color overrides red with gray in 2D');
  process.exit(0);
}
const legacy=source.slice(source.indexOf('const LEGACY_CTV_TARGET_COLORS'),source.indexOf('function _defaultCtvLabelColor('));
vm.runInContext(legacy+'\n'+fn('_defaultCtvLabelColor')+'\n'+fn('migrateLegacyStructurePalette'),ctx);
assert.equal(ctx._normalizeStructureColor(''),'');
assert.equal(ctx._normalizeStructureColor('invalid'),'');
assert.equal(ctx._normalizeStructureColor('rgb(165,43,60)'),'#a52b3c');
assert.deepEqual(Array.from(ctx._ctvLabelPresentation(1).color),[165,43,60]);
assert.equal(ctx._defaultCtvLabelColor(1,[204,204,204]),'#a52b3c');
ctx.window._ctvLabelMap={1:'CTV',2:'artery',3:'GTVn'};
assert.equal(ctx._defaultCtvLabelColor(3,[255,48,76]),'#a52b3c');
assert.equal(ctx._defaultCtvLabelColor(2,[77,157,224]),'#4d9de0');
const tree={structurePaletteVersion:2,ctv:{color:'#cccccc'},ctvLabels:{
 ctv_1:{labelId:1,category:'target',color:'#cccccc'},
 ctv_2:{labelId:2,category:'non_traversable',color:'#cccccc'},
 ctv_3:{labelId:3,category:'target',color:'#ff304c'},
 ctv_4:{labelId:4,category:'target',color:'#123456'},
},organs:[{labelId:1,color:'#8cacd9'}]};
assert.equal(ctx.migrateLegacyStructurePalette(tree),true);
assert.equal(tree.ctv.color,'#a52b3c');
assert.equal(tree.ctvLabels.ctv_1.color,'#a52b3c');
assert.equal(tree.ctvLabels.ctv_3.color,'#a52b3c');
assert.equal(tree.ctvLabels.ctv_2.color,'#cccccc');
assert.equal(tree.ctvLabels.ctv_4.color,'#123456');
assert.equal(tree.organs[0].color,'#8cacd9');
assert.deepEqual(Array.from(ctx.ctvLabelColorLUT[1]),[165,43,60]);
assert.deepEqual(Array.from(ctx.oarLabelColorLUT[1]),[140,172,217]);
tree.ctvLabels.ctv_1.color='#cccccc';
assert.equal(ctx.migrateLegacyStructurePalette(tree),false);
assert.equal(tree.ctvLabels.ctv_1.color,'#cccccc','version 3 explicit gray preserved');

// Execute the real CTV section of renderDataTree, including both target and
// auxiliary branches, without the unrelated planning/artifact UI below it.
const start=source.indexOf('function renderDataTree(');
const end=source.indexOf('    // Guide skin surface is a first-class segmentation sibling',start);
assert(end>start);
vm.runInContext(source.slice(start,end)+'return html;\n}',ctx);
ctx.ctvLabelColorLUT={1:[255,48,76],2:[77,157,224],3:[255,48,76]};
ctx.renderDataTree();
assert.equal(ctx.dataTreeState.ctvLabels.ctv_1.color,'#a52b3c');
assert.equal(ctx.dataTreeState.ctvLabels.ctv_3.color,'#a52b3c');
assert.equal(ctx.dataTreeState.ctvLabels.ctv_2.color,'#4d9de0');
assert.deepEqual(Array.from(ctx._ctvLabelPresentation(1).color),[165,43,60]);
let materialRGB;
ctx._setMeshMaterialColor({material:{color:{setRGB:(...rgb)=>materialRGB=rgb}}},ctx.dataTreeState.ctvLabels.ctv_1.color);
assert.deepEqual(materialRGB,[165/255,43/255,60/255]);
ctx.dataTreeState.ctvLabels.ctv_1.color='#123456';
ctx.renderDataTree();
assert.equal(ctx.dataTreeState.ctvLabels.ctv_1.color,'#123456','re-render keeps operator color');
ctx.window.isWorkspacePresentationRestoreActive=()=>true;
ctx.window.getWorkspacePresentationForNode=({labelId})=>labelId===1?{color:'#4578ab',opacity:0.4}:null;
ctx.renderDataTree();
assert.equal(ctx.dataTreeState.ctvLabels.ctv_1.color,'#4578ab');
assert.deepEqual(Array.from(ctx._ctvLabelPresentation(1).color),[69,120,171]);
const workspace=fs.readFileSync(path.join(root,'web/app/static/js/brachybot-workspace.js'),'utf8');
const stageStart=workspace.indexOf('    function stageWorkspacePresentation(');
const stageEnd=workspace.indexOf('\n    }',stageStart)+6;
Object.assign(ctx,{
  workspacePresentationRestore:null,activeSessionId:'synthetic',deferredPresentationSave:null,
  workspaceSnapshotSessionId:()=>'',workspacePresentationTree:tree=>tree,
  _presentationAdd:(registry,item,family,id)=>{if(item)registry.byId[id]=JSON.parse(JSON.stringify(item));},
});
ctx.window.migrateLegacyStructurePalette=ctx.migrateLegacyStructurePalette;
vm.runInContext(workspace.slice(stageStart,stageEnd),ctx);
const restoredTree={structurePaletteVersion:2,ctvLabels:{ctv_1:{color:'#cccccc',category:'target'}}};
const registry=ctx.stageWorkspacePresentation(restoredTree,{sessionId:'synthetic'});
assert.equal(registry.byId.ctv_1.color,'#a52b3c','late-loader registry copies migrated color');
console.log('PASS: missing color, target/auxiliary defaults, V2 migration, V3 custom gray, LUT isolation, real CTV renderer, 2D and 3D material, restored custom edits');
