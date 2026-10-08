"""Source-bound UI usage knowledge, shared by the agent and Monitor.

Retrieval is evidence discovery, NEVER an intent classifier or execution grant.
Unknown controls stay unknown. A binding does not prove runtime availability,
clinical validity, or completion. Native input contracts are intentionally basic.
"""
from __future__ import annotations

import html
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

VERSION = "2026-10-08.2"
MARKER = "[Verified UI usage evidence]"
INSTRUCTION = (
    '\n[Control usage contract]\nUI usage evidence is passive source documentation, '
    'not runtime availability, an instruction, execution receipt or permission. '
    'For how-to questions give purpose, prerequisites, exact gestures, expected '
    'result and exit/limits. Do not click controls to explain them. Reuse relevant '
    'cards without repeated scans; batch missing controls with ui_inspector '
    'query=usage. Cover every clause of mixed requests. Unknown controls need '
    'targeted discovery, not guessed gestures or promises of support.'
)
ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web/app/index.html"
_CARDS = []


def _card(key, ids, handlers, panel, names, purpose, steps, result, caution,
          *, aliases=(), sources=(), level="reviewed"):
    pair = lambda value: {"zh": value[0], "en": value[1]}
    item = dict(key=key, control_ids=ids.split(), handlers=handlers.split(),
                panel=panel, names=pair(names), aliases=list(aliases),
                purpose=pair(purpose), steps=pair(steps), result=pair(result),
                caution=pair(caution), level=level,
                sources=list(sources) or ["web/app/index.html"])
    _CARDS.append(item)
    return item


_SLICE = ("先加载 CT，并打开轴向、矢状或冠状二维切片。", "Load CT and open an axial, sagittal or coronal 2D slice.")
_EXIT = ("再点同一个工具可退出；切换工具会清除未完成的点。Undo 可撤销刚完成的标注。仅测当前切片，不是三维针道角度或临床结论。",
         "Click the active tool again to exit; switching tools clears unfinished points. Undo removes a completed annotation. This is a slice measurement, not a 3D needle angle or clinical conclusion.")
_GESTURES = ["web/app/static/js/brachybot-viewer-layout.js:setViewerTool",
             "web/app/static/js/brachybot-manual-annotation.js:setupAnnotationTool"]
_card("viewer.line", "toolMeasure", "", "Viewers", ("Line · 线段测距", "Line · distance"),
      ("测量同一二维切片上两点的物理距离。", "Measure physical distance between two points on one 2D slice."),
      (_SLICE[0] + "选择 Line，在起点按住鼠标左键，拖到终点后松开。",
       _SLICE[1] + " Select Line, hold the left mouse button at the start, drag to the end and release."),
      ("切片上保留线段和 mm 距离，计算使用图像间距与显示缩放。", "The slice retains a line and distance in mm, using image spacing and display scaling."),
      _EXIT, aliases=("Line", "线段测距", "测距"), sources=_GESTURES)
_card("viewer.angle", "toolAngle", "", "Viewers", ("Angle · 角度测量", "Angle · angle measurement"),
      ("测量同一二维切片上两条线段的夹角。", "Measure the angle between two segments on one 2D slice."),
      (_SLICE[0] + "选择 Angle，依次左键点第一条边上的点、顶点、第二条边上的点；第二个点是角的顶点。三个点必须在同一视图、同一切片。",
       _SLICE[1] + " Select Angle and left-click a point on the first arm, the vertex, then a point on the second arm. The SECOND point is the vertex. Keep all three points in the same view and slice."),
      ("第三点完成后显示夹角（°）；按物理像素间距计算。", "After the third point, the angle in degrees is displayed, accounting for physical pixel spacing."),
      _EXIT, aliases=("Angle", "角度测量", "量角"), sources=_GESTURES)

# Mode-specific gestures must not be inferred from a generic click contract.
for key, dom, name, purpose, steps, result, caution in [
    ("crosshair", "toolCrosshair", ("Crosshair · 十字定位", "Crosshair"),
     ("联动三张二维切片定位。", "Locate a point across the three linked slices."),
     ("加载 CT，选择 Crosshair，在二维切片中定位或拖动十字线。", "Load CT, select Crosshair and locate or drag the crosshair in a 2D slice."),
     ("其他切片联动到对应体素。", "The other slices move to the corresponding voxel."),
     ("改变浏览位置，不改变分割或规划。", "Changes navigation, not segmentation or planning.")),
    ("rect", "toolRect", ("Rect · 矩形测量", "Rect · rectangle measurement"),
     ("在二维切片画矩形测量标记。", "Draw a rectangular measurement annotation on a 2D slice."),
     (_SLICE[0]+"选择 Rect，按住左键拖出矩形后松开。", _SLICE[1]+" Select Rect, hold the left button, drag a rectangle and release."),
     ("显示矩形测量标记，不自动生成 CTV。", "Displays a measurement rectangle; does not create a CTV."), _EXIT),
    ("zoombox", "toolZoombox", ("Zoom · 框选放大", "Zoom · box zoom"),
     ("放大二维框选区域。", "Zoom into a selected 2D region."),
     (_SLICE[0]+"选择 Zoom，左键拖出足够大的矩形框后松开。", _SLICE[1]+" Select Zoom, drag a sufficiently large rectangle and release."),
     ("调整二维缩放和平移。Fit 可重新适配视野。", "Adjusts 2D zoom and pan. Fit fits the view again."),
     ("小于约 20 显示像素的框不会生效；不改变原图。", "Boxes smaller than about 20 display pixels do not apply; the image data is unchanged.")),
    ("draw", "toolAnnotate", ("Draw · 手绘掩膜", "Draw · manual mask"),
     ("手绘分割掩膜，是真实体素编辑。", "Draw a segmentation mask; this edits actual voxels."),
     (_SLICE[0]+"选择 Draw 创建活动掩膜，在二维切片上按住左键画闭合轮廓。", _SLICE[1]+" Select Draw to create an active mask, then hold the left button to draw a closed contour on a 2D slice."),
     ("轮廓填充到活动掩膜；可在 Data Tree 查看，再分类到 CTV/OAR。", "The contour is filled into the active mask, visible in Data Tree for subsequent CTV/OAR classification."),
     ("再点 Draw 或切换到其他非 Erase 工具会结束活动掩膜；Undo 撤销体素编辑。手绘结果不是临床批准。", "Click Draw again or switch to a non-Erase tool to finalize the active mask. Undo reverts voxel edits. Drawing does not confer clinical approval.")),
    ("erase", "toolEraser", ("Erase · 擦除掩膜", "Erase · mask eraser"),
     ("擦除当前活动手绘掩膜的体素。", "Erase voxels from the active manual mask."),
     ("先用 Draw 创建或绘制活动掩膜，再选择 Erase，左键圈出需要擦除的区域。", "Create or draw an active mask with Draw first, select Erase, then outline the region to erase with the left button."),
     ("活动掩膜中对应区域被擦除。", "The corresponding region is removed from the active mask."),
     ("没有活动掩膜时不执行；不是删除 Line/Angle 的工具，撤销测量请用 Undo。", "Does nothing without an active mask. It does not delete Line/Angle annotations; use Undo for measurements.")),
]:
    _card("viewer."+key, dom, "", "Viewers", name, purpose, steps, result, caution, sources=_GESTURES)
for positive, dom in [(True, "toolSat3dPositive"), (False, "toolSat3dNegative")]:
    name = "SAT3D+" if positive else "SAT3D-"
    _card("viewer.sat."+str(positive).lower(), dom, "", "Viewers", (name, name),
          (("记录前景正提示点。" if positive else "记录背景负提示点。"), "Record foreground positive prompts." if positive else "Record background negative prompts."),
          (_SLICE[0]+"选择此工具，在切片上左键点需要标记的位置。之后打开 Segment…，选择当前支持的部位并运行。",
           _SLICE[1]+" Select this tool and left-click prompt locations. Then open Segment…, choose a supported site and run inference."),
          ("先产生提示点；运行成功才产生候选分割掩膜，之后需核对并分类到 CTV/OAR。", "Prompts appear first; successful inference produces a candidate mask for review and CTV/OAR classification."),
          ("点按钮本身不会完成分割，不保证任意肿瘤可分割；Clear pts 只清提示点。", "Selecting the button does not segment anything and does not guarantee arbitrary tumor support. Clear pts clears prompts only."),
          aliases=(name,), sources=_GESTURES)


def _family(key, handlers, panel, names, purpose, steps, result, caution, ids="", **kwargs):
    return _card(key, ids, handlers, panel, names, purpose, steps, result, caution, **kwargs)


_VIEW_ONLY = ("仅调整显示，不改变原始影像、分割或剂量。", "Presentation only; does not change source images, masks or dose.")
_RECEIPT = ("以步骤结果或错误为准；点击不等于完成，已有结果也不等于临床批准。", "Use completion/error receipts; a click is not completion and an existing result is not clinical approval.")
_family("viewer.window", "applyWindowPreset applyViewerSettings", "Viewers", ("窗宽窗位 / Preset", "Window/level and Preset"),
        ("改变 CT 的灰度显示。", "Change CT grayscale presentation."),
        ("选择 Preset，或输入 W/L 后应用；W 为窗宽，L 为窗位。", "Choose Preset or apply W/L values; W is window width and L is window level."),
        ("二维 CT 灰度随之更新。", "2D CT grayscale updates."), _VIEW_ONLY)
_family("viewer.zoom", "applyZoom", "Viewers", ("二维缩放", "2D zoom"),
        ("调整二维查看缩放。", "Change 2D viewing zoom."),
        ("拖动 Zoom 滑块或两侧微调按钮；Fit 可适配视野。", "Drag the Zoom slider or use its steppers; Fit fits the view."),
        ("显示缩放百分比与切片视野更新。", "Zoom percentage and slice view update."), _VIEW_ONLY)
_family("viewer.display", "setDisplayMode toggleOverlay", "Viewers", ("显示模式 / CTV / OAR", "Display mode / CTV / OAR"),
        ("控制 CT、标签及二维叠加显示。", "Control CT, labels and 2D overlays."),
        ("用 Display 选择 CT Only、CT+Label 或 Label Only；CTV/OAR 开关与 Data Tree 的二维显示状态共同决定叠加。", "Choose CT Only, CT+Label or Label Only in Display; CTV/OAR toggles and Data Tree 2D visibility together control overlays."),
        ("对应标签在切片上显示或隐藏。", "Corresponding slice labels are shown or hidden."),
        ("需已加载标签且当前切片穿过结构；不出现不代表结构不存在。", "Requires loaded labels and a slice intersecting the structure; absence on one slice is not absence of the structure."))
_family("viewer.threshold", "applyThreshold", "Viewers", ("Threshold / HU 阈值", "Threshold / HU"),
        ("按 HU 条件创建候选掩膜。", "Create a candidate mask using an HU threshold."),
        ("加载 CT，输入有效阈值后点 Apply，检查生成区域。", "Load CT, enter a valid threshold and click Apply; inspect the generated region."),
        ("生成可进一步管理的候选掩膜。", "Produces a candidate mask for subsequent management."),
        ("阈值分割不是肿瘤诊断；使用前需检查并分类。", "Threshold segmentation is not a tumor diagnosis; review and classify it before use."))
_family("viewer.transform", "viewerFlipH viewerFlipV viewerRotate", "Viewers", ("FlipH / FlipV / Rotate", "FlipH / FlipV / Rotate"),
        ("变换二维浏览方向。", "Transform the 2D viewing orientation."),
        ("点击对应按钮翻转或旋转显示。", "Click the corresponding button to flip or rotate the display."),
        ("二维画面方向改变。", "2D presentation orientation changes."), _VIEW_ONLY)
_family("viewer.history", "viewerUndo viewerRedo", "Viewers", ("Undo / Redo", "Undo / Redo"),
        ("撤销或重做查看器编辑历史。", "Undo or redo viewer editing history."),
        ("编辑后点 Undo；需要恢复被撤销操作时点 Redo。", "Click Undo after an edit; click Redo to restore an undone operation."),
        ("针对可用历史恢复标注、提示点或掩膜事务。", "Restores annotations, prompts or mask transactions from available history."),
        ("不是通用针道/粒子规划回滚；Monitor 编辑复位使用对应版本的复位操作。", "Not a universal needle/seed plan rollback; Monitor undo uses the version-specific edit decision."))
_family("viewer.measurements.clear", "clearViewerMeasurements", "Viewers", ("清除测量", "Clear measurements"),
        ("仅清除当前病例的线段、角度和矩形测量。", "Clear line, angle and rectangle measurements in the current case only."),
        ("点击工具栏清除测量，核对数量和范围后确认；删除单项可在 Data Tree 标注行右键删除。", "Click Clear measurements, review the count and scope, then confirm; right-click an annotation row in Data Tree to delete one item."),
        ("画面和 Data Tree 同步清除，保存成功才确认完成；Undo 可整批恢复，Redo 可再次清除。", "The view and Data Tree update together; completion requires a successful save. Undo restores the batch; Redo clears it again."),
        ("不删除手绘掩膜、SAT3D 提示点、针道或粒子；无测量时禁用。清除历史截图中的标注需重新截图。", "Preserves manual masks, SAT3D prompts, needles and seeds; disabled when no measurements exist. Existing screenshots require recapture."),
        ids="toolClearMeasurements", aliases=("清除测量", "清掉测量", "clear measurements"), sources=["web/app/static/js/brachybot-manual-annotation.js:clearViewerMeasurements"])
_family("viewer.fit", "fitView", "Viewers", ("Fit · 适配视野", "Fit · fit view"),
        ("适配二维影像到视口。", "Fit 2D images to their viewports."),
        ("加载影像后点击 Fit。", "Click Fit with images loaded."),
        ("二维缩放和平移重置到适配状态。", "2D zoom and pan change to fitted presentation."), _VIEW_ONLY)
_family("viewer.reset", "resetViewer reset3DView", "Viewers", ("查看器 Reset", "Viewer Reset"),
        ("恢复对应查看器显示设置或三维相机。", "Reset the corresponding viewer presentation or 3D camera."),
        ("使用二维工具栏 Reset 或三维视图下的 Reset。", "Use Reset in the 2D toolbar or beneath the 3D view."),
        ("对应视野/显示复位。", "The corresponding view/presentation resets."),
        ("与 Input 中清空病例的 Reset 不同；不能代替规划编辑复位。", "Different from Input's case Reset; does not undo planning edits."))
_family("viewer.layout", "setViewerLayout toggleViewerFullscreen", "Viewers", ("Layout / 全屏", "Layout / fullscreen"),
        ("排列或放大查看器视口。", "Arrange or maximize viewer panes."),
        ("用 Layout 按钮选择布局，或点击视口右上角全屏按钮；再点可还原。", "Choose Layout buttons or click a pane's top-right fullscreen control; toggle again to restore."),
        ("面板布局改变，不是影像缩放。", "Pane layout changes; this is not image zoom."), _VIEW_ONLY)
_family("viewer.reconstruct", "reconstruct3D", "Viewers", ("3D · 重建", "3D · reconstruction"),
        ("构建已加载分割的三维显示。", "Build 3D presentation of loaded segmentations."),
        ("先加载 CT/标签，再点 3D，等待重建结果。", "Load CT/labels, click 3D and wait for reconstruction."),
        ("三维场景出现已加载对象。", "Loaded objects appear in the 3D scene."), _RECEIPT)
_family("viewer.slice", "updateSlice", "Viewers", ("Slice · 切片滑块", "Slice slider"),
        ("切换指定轴的切片。", "Navigate slices on the selected axis."),
        ("拖动对应视口下的 Slice 滑块或使用微调按钮。", "Drag the Slice slider below the corresponding view or use its steppers."),
        ("该轴切片和定位信息更新。", "The axis slice and location information update."), _VIEW_ONLY)
_family("viewer.surface", "toggleDoseTextureMode", "Viewers", ("Dose Surface", "Dose Surface"),
        ("切换剂量表面显示方式。", "Switch dose surface presentation."),
        ("加载剂量后点击按钮切换显示方式。", "Load dose and click the button to switch presentation."),
        ("剂量表面显示变化。", "Dose surface presentation changes."), _VIEW_ONLY)
_family("viewer.colorbar", "toggleDoseColorbarPanel closeDoseColorbarPanel resetDoseColorbarSettings applyDoseColorbarSettings syncDoseColorbarControls", "Viewers", ("Dose Scale · 剂量色标", "Dose Scale"),
        ("配置剂量显示色标范围和刻度。", "Configure dose colorbar range and ticks."),
        ("打开 Dose Scale，修改显示设置后点 Apply；Reset 恢复显示默认值，关闭按钮仅关闭面板。", "Open Dose Scale, change display settings and click Apply; Reset restores presentation defaults and Close dismisses the panel."),
        ("二维/三维剂量色标按设置显示。", "2D/3D dose colorbars use the selected presentation."),
        ("改变色标不会重算剂量，也不改变处方或 DVH 数值。", "Changing a colorbar does not recalculate dose or alter prescription/DVH values."))
_family("viewer.opacity", "setDoseOverlayOpacity update3DMeshOpacity updateDoseOpacity updateLabelImage toggle3DWireframe toggle3DSkin", "Viewers", ("透明度 / Wire / Skin / Label", "Opacity / Wire / Skin / Label"),
        ("调整剂量、网格、标签的可见性和透明度。", "Adjust dose, mesh and label visibility/opacity."),
        ("使用对应滑块或复选框；Data Tree 的对象级状态与全局显示状态共同决定最终显示。", "Use the corresponding slider or checkbox; per-object Data Tree settings and global settings jointly determine presentation."),
        ("相应图层显示立即改变。", "The corresponding layer presentation changes."), _VIEW_ONLY)
_family("viewer.sat.run", "prepareSat3dInteraction runSat3dInteractive closeSat3dInteraction clearSat3dPromptPoints", "Viewers", ("Segment… / SAT3D 提示管理", "Segment… / SAT3D prompt management"),
        ("选择部位并运行 SAT3D 交互分割。", "Select a site and run SAT3D interactive segmentation."),
        ("加载 CT，用 SAT3D+/- 放提示点，打开 Segment… 选择支持的部位后运行；Clear pts 清提示点。", "Load CT, place SAT3D+/- prompts, open Segment…, select a supported site and run; Clear pts clears prompts."),
        ("成功时返回候选掩膜；关闭面板不表示完成推理。", "Successful inference returns a candidate mask; closing the panel is not inference completion."),
        ("受模型、部位和模态可用性限制，需人工检查并分类；不是任意肿瘤的保证。", "Limited by model, site and modality availability; review and classify the candidate. No arbitrary-tumor guarantee."))

# Workflow contracts describe actual stages, not default clinical prescriptions.
for key, handlers, names, purpose, steps, outcome in [
    ("segment", "runSegmentationStep", ("CTV Seg / OAR Seg", "CTV Seg / OAR Seg"),
     ("执行选择的靶区或危及器官分割。", "Run selected target or organ-at-risk segmentation."),
     ("加载 CT，确认部位/模态和模型可用性，再点击对应分割步骤。", "Load CT, confirm site/modality and model availability, then click the corresponding segmentation step."),
     ("完成后核对 Data Tree 标签与影像对齐。", "On completion, check Data Tree labels and image alignment.")),
    ("steps", "runPlanningStep", ("Trajectories / Refine / Seeds / Dose / Evaluate", "Trajectories / Refine / Seeds / Dose / Evaluate"),
     ("逐步初始化轨迹、优化、布粒子、计算剂量和评估。", "Initialize trajectories, refine, place seeds, compute dose and evaluate step by step."),
     ("按界面前置条件从上一步到下一步执行；未满足前置条件的按钮禁用。", "Execute in prerequisite order; unavailable prerequisite steps are disabled."),
     ("每步产物出现在 Data Tree/查看器；下一步可能隐藏前一步临时预览。", "Each stage publishes outputs in Data Tree/viewers; the next stage may hide the previous temporary preview.")),
    ("run", "runPlanning", ("Start Plan", "Start Plan"),
     ("执行自动规划流程。", "Run the automated planning workflow."),
     ("准备 CT、已选择的 CTV 与所需 OAR，核对参数后点击 Start Plan。", "Prepare CT, a selected CTV and required OARs; review parameters and click Start Plan."),
     ("通过任务状态核对各阶段结果和失败信息。", "Check stage results and failures through task status.")),
    ("intra", "runIntra", ("Intraop", "Intraop"),
     ("执行术中更新工作流。", "Run the intraoperative update workflow."),
     ("准备术中输入与当前规划，核对任务需要的输入再运行。", "Prepare intraoperative inputs and the current plan; verify required inputs before running."),
     ("以术中任务实际返回的阶段结果为准。", "Use the actual returned intraoperative stage results.")),
    ("results", "showStepResults", ("Show All / View Results", "Show All / View Results"),
     ("查看已存在的阶段产物。", "View existing stage outputs."),
     ("步骤完成后点对应 Trajectories、Seeds、Dose、DVH、Metrics 或 Show All。", "After a stage completes, select Trajectories, Seeds, Dose, DVH, Metrics or Show All."),
     ("显示对应已有结果，不自动计算缺失结果。", "Displays existing outputs; missing results are not computed automatically.")),
    ("edit", "addManualNeedle addManualSeed", ("Add Needle / Add Seed", "Add Needle / Add Seed"),
     ("进入手动添加针道或粒子的流程。", "Enter manual needle/seed creation."),
     ("加载当前规划，点击对应按钮并按交互提示选择目标位置。", "Load the current plan, click the corresponding button and follow placement prompts."),
     ("提交成功后几何更新，剂量与后续产物可能过期。", "A successful commit updates geometry and may stale dose/downstream artifacts.")),
    ("dose", "recomputeManualDose", ("Recompute AI Dose", "Recompute AI Dose"),
     ("用当前已提交几何重算 AI 剂量和 DVH。", "Recompute AI dose/DVH from committed geometry."),
     ("完成并保存编辑后点击，等待剂量任务完成。", "Finish and save edits, click and wait for dose computation."),
     ("取得当前几何对应的剂量/DVH；不是独立物理验证。", "Produces dose/DVH for current geometry; not independent physics validation.")),
    ("replan", "replanManualPlan", ("Replan Geometry", "Replan Geometry"),
     ("重新规划几何，而不只是刷新显示。", "Replan geometry rather than just refresh presentation."),
     ("确认允许修改当前规划，核对参数后启动重规划。", "Confirm the current plan may be modified, review parameters and start replanning."),
     ("以任务完成后新几何和产物状态为准。", "Use resulting geometry and artifact status after task completion.")),
    ("guide", "generateSurgicalGuide", ("Generate guide", "Generate guide"),
     ("依据当前针道与导板参数生成穿刺导板。", "Generate a puncture guide from current needles and guide parameters."),
     ("完成针道编辑，核对导板参数再点击生成。", "Finish needle edits, review guide parameters and click Generate."),
     ("生成版本化导板与几何检查；针道变化后旧导板可能过期。", "Produces a versioned guide and geometry checks; needle edits may stale old guides.")),
    ("advice", "requestPlanningAdvice checkSystemReadiness", ("Detailed Advice / Readiness", "Detailed Advice / Readiness"),
     ("读取当前规划建议或系统就绪情况。", "Read current planning advice or system readiness."),
     ("点击对应按钮，查看依据和缺失的前置条件。", "Click the corresponding button and inspect evidence and missing prerequisites."),
     ("给出检查结果，不代表临床放行。", "Returns checks, not clinical clearance.")),
]:
    _family("planning."+key, handlers, "Input", names, purpose, steps, outcome, _RECEIPT)
_family("monitor.lifecycle", "startTrainingMode stopTrainingMode", "Input", ("Monitor / Finish Monitor", "Monitor / Finish Monitor"),
        ("启动或结束当前病例的操作监测。", "Start or finish operation monitoring for the current case."),
        ("点 Monitor 启动；点 Finish Monitor 结束并查看总结。", "Click Monitor to start; click Finish Monitor to finish and read the summary."),
        ("运行状态与当前病例绑定；监测提供指导，不自动批准计划。", "The run belongs to the current case; monitoring guides but does not approve a plan."),
        ("以服务端运行状态为准；反馈必须对应当前病例、运行和几何版本。", "Use server run status; feedback must match the current case, run and geometry version."))
_family("input.parameters", "applyHyperparams resetSurgicalGuideControls loadSelectedSurgicalGuideVersion", "Input", ("规划 / 导板参数与版本", "Planning / guide parameters and versions"),
        ("管理规划参数或导板显示版本。", "Manage planning parameters or the displayed guide version."),
        ("展开对应参数栏，按字段范围修改并应用；导板版本选择用于查看指定版本。", "Expand the relevant parameters, change values within field ranges and apply; guide version selection displays a selected version."),
        ("参数或显示版本更新；是否重算取决于具体执行按钮。", "Updates parameters or the displayed version; recomputation depends on the execution control."),
        ("显示默认值不是部位处方依据。旧版本不自动成为当前有效导板。", "Displayed defaults are not site-specific prescription authority. Old versions do not become current valid guides automatically."))
_family("input.reset", "resetSession", "Input", ("Input Reset · 重置病例", "Input Reset · reset case"),
        ("重置当前病例工作状态。", "Reset current case working state."),
        ("先保存需要保留的内容，再使用 Input 的 Reset 并核对确认提示。", "Save needed content before using Input Reset and review confirmation prompts."),
        ("清理/重置当前工作状态。", "Clears/resets current working state."),
        ("与查看器 Reset 不同，可能丢弃当前工作结果；不要仅为解释按钮而执行。", "Different from Viewer Reset; may discard working results. Never execute merely to explain it."))
_family("input.upload", "handleFileSelect handleDicomRTImport", "Input", ("Browse / Folder / DICOM-RT Import", "Browse / Folder / DICOM-RT Import"),
        ("上传影像或掩膜，或导入 DICOM-RT。", "Upload images/masks or import DICOM-RT."),
        ("用对应 Browse 选择文件，Folder 选择 DICOM 文件夹；DICOM-RT 使用 Import。", "Use the corresponding Browse for files, Folder for a DICOM directory, and Import for DICOM-RT."),
        ("上传结果与导入附件进入当前病例。", "Uploads/imported attachments enter the current case."),
        ("上传 mask 仅暂存，不等于已选作 CTV；需在 Data Tree 分类/选择。DICOM-RT 需核对参考坐标系和配准。", "An uploaded mask is staged, not automatically selected as CTV; classify/select it in Data Tree. Check reference frames and registration for DICOM-RT."), ids="fileCT fileCTFolder fileCTV fileOAR fileDicomRT dicomRtImportButton")
_family("export.artifacts", "exportDicomRT exportSTL exportReport exportSurgicalGuideSTL", "Input", ("DICOM-RT / STL / Report / Export Guide STL", "DICOM-RT / STL / Report / Export Guide STL"),
        ("导出对应已有产物。", "Export the corresponding existing artifact."),
        ("先生成并核对当前产物，再点击对应导出按钮。", "Generate and review the current artifact, then click the corresponding export button."),
        ("成功时提供导出文件；读取失败或过期状态需单独处理。", "Successful export provides a file; missing/stale artifacts require separate handling."),
        ("文件存在不代表临床可用；报告、剂量、网格、导板是不同产物。", "File existence is not clinical usability; reports, dose, meshes and guides are separate artifacts."))

for key, handlers, names, purpose, steps, result, caution in [
    ("fill", "Report.autoFill.fromAll", ("Auto-fill · 报告回填", "Auto-fill report"),
     ("将当前病例产物回填报告。", "Populate a report from current case artifacts."),
     ("先核对剂量/规划版本，再点击回填并审核覆盖内容。", "Check dose/plan versions, populate the report and review overwritten content."),
     ("报告字段与图件更新。", "Updates report fields and figures."), _RECEIPT),
    ("preview", "Report.preview.refreshContent Report.preview.zoomOut Report.preview.zoomIn Report.preview.zoomReset Report.panels.layout2col applyReportTemplate", ("报告模板 / Preview / Zoom", "Report template / Preview / Zoom"),
     ("管理报告模板、预览与显示缩放。", "Manage report templates, preview and presentation zoom."),
     ("选择模板并核对字段；用 Preview 刷新预览，Zoom 调整显示。", "Choose a template and check fields; Preview refreshes presentation and Zoom changes display scale."),
     ("报告预览按当前编辑显示。", "Preview reflects current edits."),
     ("预览刷新不等于重算剂量或重建导板；模板变更需检查保留字段。", "Preview refresh does not recompute dose or rebuild a guide; check retained fields after template changes.")),
    ("export", "Report.export.pdf Report.export.html Report.export.markdown Report.export.json Report._toggleExportMenu", ("报告导出", "Report export"),
     ("导出报告为所选格式。", "Export the report in the selected format."),
     ("检查报告内容和版本，选择 PDF/HTML/Markdown/JSON 导出。", "Check report contents and versions, then export PDF/HTML/Markdown/JSON."),
     ("成功时生成对应格式文件；PDF 在浏览器排版。", "Successful export generates the selected format; PDF is laid out in the browser."), _RECEIPT),
    ("review", "Report.snapshots.save Report.snapshots.openModal Report.audit.openModal Report.review.openModal Report.validation.openModal", ("报告快照 / 审计 / 审核 / 校验", "Report snapshots / audit / review / validation"),
     ("保存版本或查看报告审核、溯源和校验。", "Save versions or inspect report review, provenance and validation."),
     ("打开对应面板核对记录；保存快照时确认当前内容。", "Open the corresponding panel to inspect records; confirm current content when saving a snapshot."),
     ("显示对应记录，保存操作产生报告快照。", "Displays records; saving creates a report snapshot."),
     ("自动校验不等于医师签署批准。", "Automated validation is not signed physician approval.")),
    ("persist", "Report.persist.clear Report.persist.importJSON", ("报告清空 / Import JSON", "Clear report / Import JSON"),
     ("清空或导入报告编辑内容。", "Clear or import report editing content."),
     ("备份当前内容，核对文件和确认提示后执行。", "Back up current content and review the file/confirmation before executing."),
     ("报告编辑状态可能被替换。", "Report editing state may be replaced."),
     ("可能覆盖已有报告；不能为演示而自动执行。", "May overwrite a report; never execute automatically as a demonstration.")),
]:
    _family("report."+key, handlers, "Report", names, purpose, steps, result, caution)

_family("navigation", "switchPanel toggleSessionSidebar closeSessionSidebar newChat toggleContextPanel clearLocalChatData importLegacyWorkspace toggleHyperparams toggleStepButtons", "Global", ("面板 / 会话 / 上下文 / 参数折叠", "Panels / sessions / context / collapsible settings"),
        ("导航面板或管理会话和上下文。", "Navigate panels or manage sessions/context."),
        ("点击对应面板或会话按钮；清空、压缩、导入前核对确认与目标会话。", "Use the relevant panel/session control; review confirmation and the target session before clear, compact or import."),
        ("导航改变当前视图；管理操作按各自结果执行。", "Navigation changes the active view; management actions follow their own receipts."),
        ("切换会话不是复制病例；压缩上下文不是减少累计用量。", "Switching sessions is not copying a case; context compaction does not reduce accumulated usage."))
_family("chat.compose", "sendChat handleChatInput insertSlashCommand", "Global", ("聊天输入 / 发送 / Slash command", "Chat input / Send / slash commands"),
        ("发送当前自然语言请求。", "Send the current natural-language request."),
        ("在输入框写需求，点击发送；Enter 换行，Ctrl+Enter 或 Shift+Enter 发送。", "Write a request and click Send; Enter inserts a newline, Ctrl+Enter or Shift+Enter sends."),
        ("执行追踪展示本轮读取或操作的实际结果。", "The trace shows actual reads/actions for the turn."),
        ("解释按钮无需点击或修改病例；明确动作请求才走执行与授权校验。", "Explaining a control needs no click/case modification; action requests follow execution and authorization checks."))

# Event-bound controls have no inline handler. Bind their stable identity,
# without exposing account values or treating documentation as write authority.
_family("account.login", "", "Global", ("登录 / Sign in", "Sign in"),
        ("验证账户并进入受保护工作区。", "Authenticate an account to enter the protected workspace."),
        ("填写登录表单，按部署要求提供凭证，点击 Sign in；显示密码按钮仅切换本机显示。", "Fill in the sign-in form, supply credentials required by the deployment and click Sign in; the password visibility control only changes local display."),
        ("以认证结果为准；Remember me 受部署策略控制。", "Use authentication results; Remember me follows deployment policy."),
        ("不要向聊天发送密码或部署密钥；BrachyBot 不能代替认证或绕过账户策略。", "Do not send passwords/deployment keys to chat; the agent cannot replace authentication or bypass account policy."),
        ids="authUsername authPassword authPasswordToggle authRemember authLogin authDeploymentKey")
_family("account.management", "", "Global", ("账户 / 密码 / Sign out", "Account / Password / Sign out"),
        ("注册、修改密码或退出当前账户。", "Register, change a password or sign out."),
        ("使用对应账户面板；修改密码填写当前和新密码，Save 保存，Cancel 取消。注册是否可用取决于部署。", "Use the corresponding account panel; enter current/new passwords to change a password, Save to apply and Cancel to dismiss. Registration depends on deployment."),
        ("以服务端账户操作结果为准。", "Use server account-operation results."),
        ("不会通过聊天读取密码；登录、注销和编辑租约是不同机制。", "Passwords are not read through chat; login, logout and editing leases are separate mechanisms."),
        ids="authRegister accountPassword accountLogout currentPassword newPassword newPasswordToggle passwordSave passwordCancel")
_family("workspace.lease", "", "Global", ("接管编辑 / Take over editing", "Take over editing"),
        ("处理工作区编辑租约冲突或关闭通知。", "Handle an editing-lease conflict or dismiss a notice."),
        ("核对当前病例和其他标签页后再选择接管；x 仅关闭通知。", "Check the current case and other tabs before taking over; x only dismisses a notice."),
        ("接管是否成功以服务端租约结果为准。", "Takeover succeeds only with the server lease result."),
        ("关闭通知不获得编辑权限，也不恢复病例。", "Dismissing a notice does not acquire editing permission or restore a case."),
        ids="workspaceLockTakeover workspaceLockDismiss workspaceRecoveryDismiss importLegacyWorkspace")
_family("global.language", "window.setUiLanguage", "Global", ("中英文切换", "UI language"),
        ("切换全局显示语言。", "Switch the global presentation language."),
        ("点击顶层 EN 或 中 按钮。", "Click the top-level EN or Chinese language button."),
        ("受全局管理的界面与监测用法提示使用所选语言。", "Globally managed UI and Monitor usage hints use the selected language."),
        ("不会重算或修改病例。", "Does not recalculate or modify a case."))
_family("input.model", "", "Input", ("Tumor type / Image modality / 4D volume index", "Tumor type / Image modality / 4D volume index"),
        ("选择自动分割模型、影像模态与四维输入的体积索引。", "Select automatic segmentation model, image modality and the volume index of a 4D input."),
        ("选择与实际影像相符的部位/模态；四维单模态文件选择有效索引，再执行分割。", "Choose site/modality matching the actual image; select a valid volume index for a 4D single-modality file before segmentation."),
        ("选择影响下一次模型调用，不会仅因选择自动完成推理。", "Selections affect the next model call; selecting does not finish inference."),
        ("遵从模型可用性与模态要求；鼻咽 NCCT/CECT 不可混选。", "Respect model availability and modality requirements; do not interchange nasopharynx NCCT/CECT."),
        ids="ctvModelSelect ctvImageModality ctvVolumeIndex")
_family("input.paths", "", "Input", ("CT / CTV / OAR / DICOM-RT 路径", "CT / CTV / OAR / DICOM-RT paths"),
        ("显示或输入当前病例输入路径。", "Display or enter current case input paths."),
        ("优先用 Browse/Folder 上传；已有服务器路径必须在授权范围内。", "Prefer Browse/Folder uploads; an existing server path must be within authorized scope."),
        ("显示输入来源，需检查对应资源是否成功加载。", "Displays input provenance; check the corresponding resource has loaded successfully."),
        ("填入路径不等于上传、分类、分割或计算完成。", "Entering a path is not upload, classification, segmentation or calculation completion."),
        ids="ctPath ctvPath oarPath dicomRtPath")
_family("guide.import-validation", "", "Input", ("Validate Imported STL", "Validate Imported STL"),
        ("选择导入 STL 并进行网格校验。", "Select an imported STL for mesh validation."),
        ("点击 Validate Imported STL，选择文件，再查看校验结果。", "Click Validate Imported STL, choose a file and inspect validation results."),
        ("返回导入网格检查结果，不替换成已批准导板。", "Returns imported-mesh checks, not an approved guide."), _RECEIPT,
        ids="guideStlValidationFile")

# Explicit native-input families. They provide UI editing contracts only,
# not invented algorithm explanations or clinical dose recommendations.
_NATIVE_GROUPS = [
    ("seed", "devThreshold useRLToggle seedRadius seedLength seedCountMin seedCountMax seedMarginRate seedAvgDose", "Input", ("粒子 / 规划模式参数", "Seed / planning-mode parameters")),
    ("labels", "targetValue obstacleValue backgroundValue", "Input", ("Target / Obstacle / Background 标签值", "Target / Obstacle / Background label values")),
    ("direction", "backlitAngle maxCandiTraj refDirecX refDirecY refDirecZ refDirecAuto direcResCone direcResStep direcResRings", "Input", ("参考方向 / 轨迹候选参数", "Reference direction / trajectory candidates")),
    ("dose", "inLowestEnergy outHighestEnergy dvhRate maxIter", "Input", ("剂量 / DVH 规划约束", "Dose / DVH planning constraints")),
    ("optimizer", "distLowerBound distUpperBound distRate intervalRate iterRate replanRate dlLR dlLRDecay dlEpochs dlPatience dlSearchRegion dlDVHMargin inferSizeX inferSizeY inferSizeZ rfMaxEpisodes rfBandwidth", "Input", ("优化 / 推理参数", "Optimization / inference parameters")),
    ("guide", "guideSkinThreshold guideSkinClearance guidePlateThickness guidePatchMargin guideChannelDiameter guideSleeveOuterDiameter guideSleeveOutward guideSleeveInward guideGeometryResolution guideAuxiliaryHolesEnabled guideAuxiliaryHoleDiameter guideAuxiliaryHoleRingCount guideAuxiliaryHolesPerRing guideAuxiliaryHoleFirstOffset guideAuxiliaryHoleRingSpacing guideNeedleSelection guideVersionSelect surgicalGuidePlanningSelect", "Input", ("导板参数 / 针道选择 / 版本", "Guide parameters / needle selection / version")),
    ("display", "viewerThreshold doseColorbarMinInput doseColorbarMaxInput doseColorbarPalette sat3dInteractiveSite", "Viewers", ("阈值 / 色标 / SAT3D 部位输入", "Threshold / colorbar / SAT3D site inputs")),
]
for key, ids, panel, names in _NATIVE_GROUPS:
    _family("fields."+key, "", panel, names,
            ("编辑对应表单设置；详细单位和允许范围以该字段说明为准。", "Edit the corresponding form settings; use each field's documented units and allowed range."),
            ("在字段中输入值或选择选项，遵从 min/max/step；核对后使用相应 Apply、运行或生成按钮。", "Enter a value or select an option, respecting min/max/step; review it, then use the appropriate Apply, Run or Generate control."),
            ("先改变待应用设置；不把修改字段说成已经完成规划或重算。", "Changes pending settings; editing a field is not completed planning or dose recomputation."),
            ("这是基础输入操作契约，不是已验证的临床推荐或参数最优值。", "This is a basic input-editing contract, not a validated clinical recommendation or optimal parameter value."),
            ids=ids, level="basic_input")


_family("global.theme", "", "Global", ("主题 / Theme", "Theme"),
        ("切换明暗显示主题。", "Switch light/dark presentation theme."),
        ("点击顶层主题图标。", "Click the top-level theme icon."),
        ("界面显示主题更新。", "The presentation theme updates."), _VIEW_ONLY)
_STATIC_COUNT = len(_CARDS)
for key, names, purpose, steps, result, caution, aliases in [
    ("visibility", ("Data Tree · 显示 / 隐藏", "Data Tree · show / hide"),
     ("控制对应对象显示。", "Control presentation of the corresponding object."),
     ("核对目标行后点击眼睛图标；二维显示使用右键菜单 Show in 2D，三维使用对应显示项。", "Check the target row, then click its eye icon; use Show in 2D in its context menu for slices, or the corresponding 3D visibility action."),
     ("对应维度可见性更新，受上级组、全局叠加和切片位置共同影响。", "Visibility updates on the corresponding surface, subject to group/global overlays and slice location."),
     ("隐藏不等于删除；二维切片需与结构相交。动作需绑定当前对象稳定 ref。", "Hidden is not deleted; a 2D slice must intersect the structure. Actions require the current object's stable ref."),
     ("眼睛图标", "Show in 2D", "Show in 3D", "二维显示")),
    ("opacity", ("Data Tree · 对象透明度", "Data Tree · object opacity"),
     ("调整指定对象或组的显示透明度。", "Adjust presentation opacity for a specified object or group."),
     ("在目标行拖动透明度滑块，或点两侧三角形微调。", "Drag the target row's opacity slider or use its triangular steppers."),
     ("查看器相应对象显示变化；不重算剂量。", "The corresponding viewer object's presentation changes; dose is not recalculated."), _VIEW_ONLY,
     ("data tree opacity", "数据树透明度", "透明度滑块")),
    ("color", ("Data Tree · 颜色", "Data Tree · color"),
     ("修改对应结构的显示颜色。", "Change a structure's presentation color."),
     ("在目标行点击颜色按钮，选择颜色并确认。", "Click the target row's color control, choose a color and confirm."),
     ("结构显示及已关联的 DVH/Analysis 呈现应采用同一颜色。", "Structure presentation and linked DVH/Analysis presentation should use the same color."), _VIEW_ONLY,
     ("data tree color", "数据树颜色", "更改颜色")),
    ("classify", ("Data Tree · 掩膜分类", "Data Tree · mask classification"),
     ("将上传/手绘候选掩膜分类为 CTV 或 OAR。", "Classify uploaded/manual candidate masks as CTV or OAR."),
     ("核对掩膜与 CT 对齐、标签含义和目标行，在右键菜单选择对应分类。", "Verify CT alignment, label semantics and the target row, then select the corresponding classification in its context menu."),
     ("结构语义和规划输入改变；仅上传不等于 CTV 就绪。", "Changes structure semantics and planning inputs; upload alone is not CTV readiness."),
     ("可能使规划产物过期；不能把不同来源的 label 2 统一解释为障碍物。", "May stale planning artifacts; label 2 from different sources must not be universally interpreted as an obstacle."),
     ("move to CTV", "move to OAR", "掩膜分类", "移到CTV", "移至CTV")),
    ("manage", ("Data Tree · 重命名 / 删除 / 组管理", "Data Tree · rename / delete / groups"),
     ("管理指定对象的名称、归组或移除。", "Manage a specified object's name, group or removal."),
     ("右键目标行，选择对应操作并核对确认；组操作影响其成员。", "Right-click the target row, select the operation and review confirmation; group operations affect members."),
     ("以对应对象的实际操作结果为准。", "Use the actual result for the specified object."),
     ("删除与隐藏不同；自然语言执行必须解析当前稳定对象 ID 和授权范围。", "Deletion differs from hiding; natural-language execution requires the current stable object ID and authorized scope."),
     ("数据树重命名", "data tree rename", "数据树删除", "data tree delete")),
]:
    _card("tree."+key, "", "", "Viewers", names, purpose, steps, result, caution,
          aliases=aliases, sources=["web/app/static/js/brachybot-ui-api.js:collectUIOperationCatalog",
                                   "web/app/static/js/brachybot-viewer-volume.js"])


def _normal(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(text or "")))).strip().casefold()


def _contains(text, alias):
    alias = _normal(alias)
    if not alias:
        return False
    if re.fullmatch(r"[a-z0-9_. +/\-]+", alias):
        return re.search(r"(?<![a-z0-9_])"+re.escape(alias)+r"(?![a-z0-9_])", text) is not None
    return len(alias) >= 2 and alias in text


@lru_cache(maxsize=8)
def _mounted(stamp):
    """Parse only actual interactive elements; no arbitrary JS/source search."""
    from html.parser import HTMLParser
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows = []; self.current = None
        def handle_starttag(self, tag, attrs):
            if tag in {"button", "input", "select", "textarea"}:
                row = dict(attrs); row["tag"] = tag; row["text"] = ""
                if row.get("type") != "hidden": self.rows.append(row)
                self.current = row if tag != "input" else None
        def handle_data(self, text):
            if self.current is not None: self.current["text"] += " "+text
        def handle_endtag(self, tag):
            if tag in {"button", "select", "textarea"}: self.current = None
    parser = Parser(); parser.feed(HTML.read_text(encoding="utf-8"))
    return parser.rows


def _bound(card, row):
    if card['key'] == 'global.language' and 'data-lang-btn' in row:
        return True
    if card['key'] == 'global.theme' and 'data-theme-toggle' in row:
        return True
    if row.get("id") in card["control_ids"]:
        return True
    handlers = " ".join(str(row.get(k) or "") for k in ("onclick", "onchange", "oninput", "onkeydown"))
    trigger = re.search(r"document\.getElementById\(['\"]([^'\"]+)['\"]\)\.click\(\)", handlers)
    if trigger and trigger.group(1) in card['control_ids']:
        return True
    return any(re.search(r"(?<![\w.])"+re.escape(fn)+r"\s*\(", handlers) for fn in card["handlers"])


def catalog():
    # Keep cached knowledge immutable across cases/callers.
    return deepcopy(_catalog(HTML.stat().st_mtime_ns))


@lru_cache(maxsize=8)
def _catalog(stamp):
    rows = _mounted(stamp)
    cards = []
    for index, source in enumerate(_CARDS):
        bound = [row for row in rows if _bound(source, row)]
        if not bound and index < _STATIC_COUNT:
            continue  # Deleted/unmounted documentation is not current UI evidence.
        item = dict(source)
        item["bindings"] = [{"id": row.get("id"), "label": row.get("data-i18n-en") or _normal(row.get("text")) or row.get("title") or row.get("id"),
                             "disabled_by_default": "disabled" in row,
                             "tag": row["tag"], "input_constraints": {k: row[k] for k in ('type', 'min', 'max', 'step', 'accept') if k in row}} for row in bound]
        cards.append(item)
    return cards


def lookup(requests, *, panel="", limit=8):
    """Exact identities and whole-word aliases outrank family-name matches."""
    requests = [requests] if isinstance(requests, str) else list(requests or [])[:16]
    ranked = {}
    for query in requests:
        text = _normal(query)
        for card in catalog():
            if panel and _normal(panel) not in {_normal(card["panel"]), "all"}:
                continue
            identities = [card["key"], *card["control_ids"]]
            labels = [b["label"] for b in card["bindings"] if b.get("label")]
            aliases = [*card["aliases"], *card["names"].values()]
            aliases += [v.split(' · ')[0].strip() for v in card['names'].values()]
            # Slash-separated family names also expose exact individual labels.
            aliases += [s.strip() for v in card["names"].values() for s in v.split("/") if len(s.strip()) > 2]
            score = 100 if any(text == _normal(s) for s in identities+labels+aliases) else (
                80 if any(_contains(text, s) for s in identities+card["aliases"]) else
                60 if any(_contains(text, s) for s in labels+aliases) else 0)
            if score: ranked[card["key"]] = (max(score, ranked.get(card["key"], (0,))[0]), card)
    ordered = sorted(ranked.values(), key=lambda pair: (-pair[0], pair[1]["key"]))
    return [item for _, item in ordered[:max(1, min(int(limit), 16))]]


def compact(card, language="en"):
    lang = "zh" if str(language).lower().startswith("zh") else "en"
    return {"key": card["key"], "control_ids": card["control_ids"], "panel": card["panel"],
            "name": card["names"][lang], "purpose": card["purpose"][lang],
            "steps": card["steps"][lang], "expected_result": card["result"][lang],
            "limits_and_exit": card["caution"][lang], "level": card["level"], "sources": card["sources"],
            "input_constraints": {b['id']: b['input_constraints'] for b in card['bindings'] if b.get('id') and b['input_constraints']},
            "runtime_availability": "not_observed", "authorization": "none"}


def usage_packet(requests, *, panel="", language="en", limit=8):
    candidates = lookup(requests, panel=panel, limit=16)
    cards = candidates[:max(1, min(int(limit), 16))]
    return {"manual_version": VERSION, "basis": "source_bound_usage_not_runtime_receipt",
            "cards": [compact(c, language) for c in cards],
            "matched_cards": len(candidates), "more_matches": len(candidates) > len(cards),
            "unresolved": [q for q in ([requests] if isinstance(requests, str) else list(requests or [])[:16])
                           if not lookup(q, panel=panel, limit=1)]}


def manual_index(panel="", language="en"):
    """Discover topics without sending the entire manual or clinical state."""
    lang = 'zh' if str(language).lower().startswith('zh') else 'en'
    return [{'key':c['key'], 'name':c['names'][lang], 'panel':c['panel'], 'level':c['level']}
            for c in catalog() if not panel or _normal(c['panel']) == _normal(panel)]


def render_cards(cards):
    return "\n\n".join(f"**{c['name']}**\n\n{c['purpose']}\n\n{c['steps']}\n\n{c['expected_result']}\n\n{c['limits_and_exit']}" for c in cards)


def bounded_evidence_json(payload, budget=3800):
    """Keep provider evidence valid and explicitly partial, never cut a card.

    The function-call loops currently cap internal tool text at 4k characters.
    Drop whole catalogue/usage rows before that boundary; never slice a stable
    ref, action argument or instruction into a misleading partial value.
    Typed ToolResult.data is unchanged. Very large scalar-only evidence fails
    closed instead of becoming invalid JSON or a fabricated empty catalogue.
    """
    value = deepcopy(payload)
    omitted = {}
    lists = {'cards', 'manual_index', 'static_actions_not_runtime_availability',
             'included', 'unresolved', 'workflows', 'matched_actions'}
    encode = lambda: json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
    def candidates(node, path=()):
        if not isinstance(node, dict):
            return
        for key, item in node.items():
            if key in lists and isinstance(item, list) and item:
                yield path+(key,), item
            elif isinstance(item, dict):
                yield from candidates(item, path+(key,))
    while len(encode()) > budget:
        choices = list(candidates(value))
        if not choices:
            return json.dumps({'basis':payload.get('basis', 'bounded_inspector_projection'),
                               'projection_too_large':True,
                               'next_read':'Use a narrower stable control key or object ref; this is not an empty-state or completion receipt.'})
        path, rows = max(choices, key=lambda pair:len(json.dumps(pair[1][-1], ensure_ascii=False, default=str)))
        name = '.'.join(path)
        omitted.setdefault(name, {'total':len(rows), 'included':len(rows)})
        rows.pop()
        omitted[name]['included'] = len(rows)
        value['projection_truncation'] = omitted
        value['next_read'] = 'Read omitted controls by stable key/ref with a narrower component or usage query; omitted is not absent.'
    return encode()


def context_evidence(request, language="en"):
    # Bounded passive retrieval for ALL speech acts. The model still interprets
    # the whole request; mentioning a control never starts that control.
    packet = usage_packet(request, language=language, limit=5)
    return MARKER+"\n"+bounded_evidence_json(packet, budget=6000) if packet["cards"] else ""


def usage_only_fallback(request, language="en", steps=()):
    """Conservative incomplete-turn recovery, not a normal request router.

    Do not substitute a usage answer for mixed tasks, runtime diagnostics,
    clinical questions, or a turn that attempted an action.
    """
    text = _normal(request)
    if not re.search(r"怎么用|如何使用|如何操作|怎样操作|什么用途|做什么|有何区别|区别是什么|how (?:do|can|to|does)|how .*work|what .* (?:do|for)|difference between", text):
        return ""
    if re.search(r"然后|接着|顺便|帮我(?:把|执行|启动|生成|删除|隐藏|显示|设置)|and then|also (?:run|start|delete|show)|please (?:run|start|delete|show)|为什么|why|疗效|处方|耐受|dose.*(?:safe|limit)", text):
        return ""
    if any(s.get("type") == "tool" and s.get("tool") not in {"ui_inspector"}
           and s.get("tool_name", s.get("tool")) != "ui_inspector" for s in steps):
        return ""
    packet = usage_packet(request, language=language, limit=5)
    if not packet["cards"]:
        return ""
    prefix = "已能核实的控件用法如下；本轮未完成其他内容或现场状态的核验：\n\n" if language == "zh" else "The control usage verified so far is below; other content or live-state checks were not completed this turn:\n\n"
    return prefix+render_cards(packet["cards"])


def coverage():
    rows = _mounted(HTML.stat().st_mtime_ns)
    cards = catalog()
    unknown = [{"id": r.get("id"), "tag": r["tag"], "label": r.get("data-i18n-en") or _normal(r.get("text")) or r.get("id"),
                "handler": next((r.get(k) for k in ("onclick", "onchange", "oninput") if r.get(k)), None)}
               for r in rows if not any(_bound(c, r) for c in cards)]
    return {"version": VERSION, "interactive_controls": len(rows), "reviewed_cards": len(cards),
            "source_bound_controls": len(rows)-len(unknown), "unknown_controls": unknown,
            "dynamic_controls": "Require live ui_operations stable refs; no invented bindings."}
