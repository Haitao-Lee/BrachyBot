"""Code-based zh/en presentation for timepoint control and scoped runtimes.

Presentation is separate from technical codes, identifiers, and saved names.
Language comes from an explicit supported locale or existing shared memory;
never detect it from a title, request text, or exception. This module neither
loads an agent nor hydrates clinical arrays. Unknown codes have a safe generic
message, and exception text is never part of a public message.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re

from memory.language import normalize_language


LANGUAGE_HEADER = "X-BrachyBot-Language"
SUPPORTED_LANGUAGES = frozenset({"zh", "en"})
_LOCALE = re.compile(r"[A-Za-z]{2}(?:[-_][A-Za-z0-9]{2,8}){0,3}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}\Z")
_IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")

# Each message uses reviewed fixed text. Only a typed count can be formatted;
# no arbitrary exception, path, user name, or request string is interpolated.
_MESSAGES = {
    'archive_storage_unavailable': ('归档存储暂时不可用，未删除或替换病例数据。请恢复归档存储连接后重试激活；这不代表病例已经丢失。',
        'Archive storage is temporarily unavailable; case data was not deleted or replaced. Restore the archive storage connection, then retry activation. This does not establish that the case is lost.'),
    'planning_config_invalid': ('规划参数无效，未保存更改。请检查粒子尺寸、剂量、覆盖率、方向和参数范围后重试。',
        'Planning parameters are invalid; changes were not saved. Check source dimensions, dose, coverage, direction and parameter ranges, then retry.'),
    'continuation_source_geometry_mismatch': ('新增规划粒子的尺寸或源描述与已复核的体内粒子基线不一致，未继续规划。请核对 Input 与体内粒子源设置；如需改变物理源参数，须重新确认并重算基线。粒子间距参数可独立调整。',
        'Supplemental-source dimensions or source settings differ from the reviewed implanted baseline; planning was not continued. Check Input and implanted-source settings. Reconfirm changed physical source parameters and recompute the baseline. Placement spacing can be adjusted independently.'),
    'total_dose_export_stale': ('总剂量已失效。请先重算当前粒子的剂量，再导出；未导出旧剂量。',
        'Total dose is stale. Recompute current source dose before exporting; stale dose was not exported.'),
    'preoperative_timepoint_required': ('当前窗口是术中时间点，不能执行从零开始的术前规划。请使用术中重新规划，或切换到术前时间点；当前粒子和剂量未改动。',
        'This workspace is intraoperative; zero-baseline preoperative planning was not started. Use intraoperative replanning or switch to a preoperative timepoint. Current sources and dose were not changed.'),
    'intraoperative_timepoint_required':('请先选择或新建术中时间点，并关联对应术前方案、上传当前术中影像。当前术前时间点未改动。',
        'Select or create an intraoperative timepoint, link its preoperative plan and upload the current intraoperative image. The current preoperative timepoint was not changed.'),
    'planning_reference_input_mismatch':('所提交的影像与当前时间点的规划参考不一致。请核对 Image 中的规划参考选择，刷新后重试；未改动分割或规划。',
        'The submitted image does not match this timepoint\'s planning reference. Check the reference selection under Image, reload and retry; segmentation and planning were not changed.'),
    'continuation_preoperative_plan_required':('关联的术前时间点尚无非空规划，未启动术中增量规划。请先完成该术前来源的规划，或为不需要关联的独立规划新建术前时间点。体内粒子识别和单独剂量重算仍可使用。',
        'The linked preoperative timepoint has no nonempty plan; intraoperative continuation was not started. Complete its preoperative plan, or create a preoperative timepoint for independent planning. Implant detection and source-only dose recomputation remain available.'),
    'guide_registration_invalid':('导板定位或复核未完成。请核对关联术前时间点、实际打印导板标识、配准证据、候选定位及复核说明；接受定位前必须检查当前 2D／3D 叠加。',
        'Guide placement or review did not complete. Check the linked preoperative timepoint, physical printed-guide ID, registration evidence, placement candidate and review note. Inspect current 2D/3D overlays before accepting a fit.'),
    'guide_registration_conflict':('导板定位输入或编辑状态已变更，未应用过期定位。请刷新当前时间点并重新核对。',
        'Guide placement inputs or editing state changed; a stale placement was not applied. Reload the current timepoint and review it again.'),
    'guide_source_image_unverified':('无法核验制作该打印导板的原始术前影像，未使用当前参考图像替代。请恢复原始上传及关联计划记录后重新估计；若术中能观察导板，可选择“重建当前 CT 中可见导板”并明确其区域。已有影像配准候选须重新估计和复核。',
        'The original preoperative acquisition for this printed guide could not be verified; the current reference was not substituted. Restore the original upload and linked Planning record, then estimate again. If the guide is visible in the current CT, select visible-guide reconstruction and specify its ROI. Previous image-derived candidates must be re-estimated and reviewed.'),
    'component_dose_recompute_failed': ('剂量分量重算未完成，未发布新的总剂量或规划指标。请核对当前影像、体内粒子复核、源尺寸和规划粒子，修正后重试。',
        'Component-dose recomputation did not finish; no new total dose or plan metrics were published. Check the current image, implanted-source review, source dimensions and planned sources, then retry.'),
    'dose_source_set_invalid': ('请选择体内粒子、新增规划粒子或二者的总剂量。',
        'Select implanted sources, supplemental planned sources or their total dose.'),
    'component_dose_recomputed': ('已重算当前粒子的剂量分量，并保存可用的总剂量与指标；没有执行额外的下游任务。',
        'Current source-dose components and available total dose/metrics were saved; no extra downstream task was executed.'),
    "implant_review_required": ("当前影像的体内粒子已识别并保存。请先复核粒子、方向和完整扫描范围；尚未新增粒子或重新规划。", "Implanted observations are detected and saved on the current image. Review sources, axes and scan coverage first; no supplemental sources or plan have been generated."),
    "continuation_profile_required": ("请先在术中设置中确认针半径、导向长度、障碍物间隙和最大穿刺深度，再进行增量规划。", "Confirm needle radius, guiding length, obstacle clearance and maximum insertion depth in intraoperative settings before continuation."),
    "continuation_guide_review_required": ("已计算体内粒子的基线剂量。现有导板尚未完成术中刚性定位复核，请确认导板位置后再规划剩余路径。", "Implanted baseline dose is computed. The printed guide still needs intraoperative rigid-placement review before planning its remaining channels."),
    "implant_dose_source_ambiguous": ("当前同时有规划粒子和体内识别粒子。请明确只计算体内已有粒子，还是计算当前规划粒子。", "Both planned and observed implanted sources exist. Specify existing implanted sources only or the current planned sources."),
    "implant_source_parameters_required": ("尚未保存当前时间点的粒子尺寸与剂量源设置。请先确认源参数；不会借用术前参数或猜测尺寸。", "Current-timepoint source dimensions and dose settings are not saved. Confirm them first; preoperative settings and guessed dimensions are not substituted."),
    "implant_axis_unavailable": ("至少一颗粒子的方向不能可靠重建。请复核其方向后重算，未跳过该粒子。", "At least one source axis could not be reconstructed. Review its direction and retry; that seed was not skipped."),
    "implant_dose_model_unavailable": ("当前剂量 CNN 模型不可用，未生成模拟或替代剂量。", "The dose CNN is unavailable; no simulated or substitute dose was generated."),
    "implant_dose_inputs_invalid": ("体内粒子剂量输入或标定信息不完整，请核对当前识别记录与源配置。", "Implanted-dose input or calibration is incomplete. Check current observations and source configuration."),
    "implant_dose_recomputed": ("已用当前修订的体内粒子重算 CNN 剂量。未新增粒子、未重新规划针道、未生成导板或报告；估计方向和源参数仍需临床复核。", "CNN dose was recomputed from the current edited implanted observations. No sources, needle plan, guide or report were generated. Estimated axes and source assumptions still require clinical review."),
    "implant_view_ready": ("识别记录已保存并准备好重建显示；逐颗复核后再用于剂量计算。", "Observations are saved and ready for reconstruction display. Review each seed before dose calculation."),
    "implant_edit_tools_opened": ("已请求打开粒子识别修正工具；2D 点击定位后可在 3D 微调并保存。", "Requested observation correction tools. Select a center in 2D, refine it in 3D, then save."),
    "implant_service_not_bound": ("粒子识别尚未绑定已验证的时间点工作区。", "Seed detection is not bound to an authenticated timepoint workspace."),
    "implant_reconstruction_not_found": ("尚无此时间点的粒子识别记录，请先执行识别。", "No observations are saved for this timepoint. Run detection first."),
    "implant_image_required": ("请先上传并加载当前时间点的 CT 图像。", "Upload and load the current timepoint CT first."),
    "implant_reference_not_ready": ("此图像集合尚需明确且已接入的规划参考图像，未猜测使用其他图像。", "This image collection requires an integrated explicit reference; no other image was guessed."),
    "implant_revision_conflict": ("识别记录已变更，未保存过期修正。请刷新并重新核对。", "Observations changed; a stale correction was not saved. Reload and review again."),
    "implant_input_changed": ("原识别记录对应的图像已变更，未应用旧记录。请识别当前图像。", "The observation image changed. Old records were not applied; detect the current image."),
    "implant_presentation_conflict": ("显示设置已在其他窗口变更，请刷新后重试。", "Presentation changed in another window. Reload and retry."),
    "implant_center_outside_image": ("修正位置在当前 CT 范围之外，未保存。", "The correction is outside the current CT and was not saved."),
    "implant_duplicate_center": ("该位置已有粒子识别记录，未重复添加。", "An observation already exists at that position; no duplicate was added."),
    "implant_job_in_progress": ("此时间点正在执行粒子识别，请等待完成后再修正。", "Detection is running for this timepoint. Wait before correcting it."),
    "implant_job_not_found": ("识别任务不再运行，请刷新已保存记录；未提交的任务需要重新启动。", "The detection worker is no longer running. Reload saved records; restart an uncommitted job."),
    "implant_observation_not_found": ("此粒子不在当前识别记录中，请刷新后重试。", "This seed is absent from the current observations. Reload and retry."),
    "implant_review_authorization_required": ("临床复核需独立的已验证人工操作，模型调用不能自动批准。", "Clinical review requires an authenticated human action; a model call cannot approve it."),
    "invalid_implant_presentation": ("粒子显示设置无效，请核对颜色、透明度及版本。", "Invalid seed presentation; check color, opacity and revision."),
    "seedfinder_not_configured": ("服务端 SeedFinder 模型尚未配置，未执行推理。", "Server SeedFinder is not configured; inference was not run."),
    "implant_operation_failed": ("粒子操作未完成；请检查目标、模型配置与服务端记录，未确认临床可用性。", "The observation operation did not complete. Check target, model configuration and server records; clinical readiness is not confirmed."),
    "authentication_required": (
        "此请求需要有效的身份验证。",
        "Valid authentication is required for this request.",
    ),
    "access_denied": (
        "无法核验此请求的授权，请刷新登录状态后重试。",
        "Request authorization could not be verified. Refresh authentication and retry.",
    ),
    "invalid_api_key": (
        "此请求需要有效的 API 密钥。",
        "A valid API key is required for this request.",
    ),
    "invalid_workspace_request": (
        "工作区请求无效，请检查目标标识、请求字段和版本号。",
        "The workspace request is invalid. Check its target identifiers, fields, and revision.",
    ),
    "invalid_timepoint": (
        "时间点请求无效，请检查名称、阶段、来源时间点和版本号。",
        "The timepoint request is invalid. Check its title, stage, source timepoint, and revision.",
    ),
    "invalid_timepoint_scope": (
        "会话或时间点标识冲突或无效，请为请求指定同一个明确目标。",
        "Conflicting or invalid Session/timepoint identifiers. Use one explicit target for the request.",
    ),
    "timepoint_not_found": (
        "此时间点或所属会话不可用，请刷新目录并确认当前会话。",
        "This timepoint or its Session is unavailable. Refresh the catalog and confirm the selected Session.",
    ),
    "timepoint_dependencies": (
        "其他时间点仍引用此时间点，请先检查依赖关系再删除。",
        "Other timepoints still reference this timepoint. Review its dependencies before deletion.",
    ),
    "timepoint_conflict": (
        "时间点状态已变更，或当前操作需要先解决依赖或迁移条件；请重新加载后检查。",
        "The timepoint state changed, or this operation requires dependency or migration review. Reload it and check.",
    ),
    "workspace_conflict": (
        "当前工作区暂不允许此操作，请检查编辑占用和归档状态后重试。",
        "This operation is currently unavailable for the workspace. Check its editing lease and archive status before retrying.",
    ),
    "workspace_lease_conflict": (
        "另一浏览器正在编辑此会话，请先释放编辑占用再重试。",
        "Another browser is editing this Session. Release the editing lease before retrying.",
    ),
    "workspace_archived": (
        "此会话已归档，请激活后再使用其工作区数据。",
        "This Session is archived. Activate it before using its workspace data.",
    ),
    "timepoint_integrity_error": (
        "无法安全读取此时间点的已保存状态，请检查服务端保存记录。",
        "The saved timepoint state could not be read safely. Check the server's saved-state records.",
    ),
    "timepoint_execution_not_ready": (
        "时间点执行尚未启用；请等待运行时完成目标范围接入。",
        "Timepoint execution is not enabled yet. Runtime target scoping must be completed first.",
    ),
    "timepoint_tool_not_ready": (
        "此操作的时间点接入尚未就绪，未在其他时间点执行。请保留目标时间点并稍后重试。",
        "This operation's timepoint adapter is not ready. It was not executed on another timepoint. Retain the target and retry after integration.",
    ),
    "timepoint_target_confirmation_required": (
        "请求的写入目标与提交时的时间点不同，尚未执行。请先切换到确认的目标时间点，再重新提交；只读跨时间点比较不受此限制。",
        "The write target differs from the submission timepoint; nothing was executed. Select the confirmed target and resubmit. Read-only comparisons are still available.",
    ),
    "timepoint_workspace_unbound": (
        "此操作需要绑定已验证身份的会话工作区。",
        "This operation requires a bound, authenticated Session workspace.",
    ),
    "timepoint_json_required": (
        "请提供 JSON 对象作为请求正文。",
        "Provide a JSON object as the request body.",
    ),
    "timepoint_browser_patch_invalid": (
        "浏览器请求只能更新该时间点的界面和报告状态。",
        "Browser requests can update only this timepoint's UI and report state.",
    ),
    "timepoint_inspector_invalid_fields": (
        "时间点查询仅接受 action 和 timepoint_ids 字段。",
        "Timepoint inspection accepts only action and timepoint_ids.",
    ),
    "timepoint_inspector_action_required": (
        "请选择只读操作 list 或 inspect。",
        "Select the read-only list or inspect action.",
    ),
    "timepoint_inspector_targets_required": (
        "查询已保存状态时，请提供目录中 1 至 16 个明确的时间点 ID。",
        "To inspect saved state, provide 1 to 16 explicit timepoint IDs from the catalog.",
    ),
    "timepoint_inspector_duplicate_targets": (
        "时间点查询目标不能重复。",
        "Timepoint inspection targets must not contain duplicates.",
    ),
    "timepoint_catalog_loaded": (
        "已读取时间点目录。",
        "Read the timepoint catalog.",
    ),
    "timepoint_created": ("已创建时间点。", "Created the timepoint."),
    "timepoint_updated": ("已更新时间点元数据。", "Updated the timepoint metadata."),
    "timepoint_delete_impact_loaded": (
        "已读取删除此时间点的依赖影响。",
        "Read the dependency impact of deleting this timepoint.",
    ),
    "timepoint_deleted": (
        "时间点已移入可恢复的删除状态。",
        "The timepoint is in the recoverable deleted state.",
    ),
    "timepoint_restored": ("时间点已恢复为活动状态。", "The timepoint is active again."),
    "timepoint_workspace_loaded": (
        "已读取时间点的已保存工作区状态；未重新执行临床计算。",
        "Read the saved timepoint workspace state; no clinical calculation was rerun.",
    ),
    "timepoint_workspace_saved": (
        "已保存时间点的界面和报告状态。",
        "Saved the timepoint's UI and report state.",
    ),
    "timepoint_inspector_listed": (
        "已读取当前会话的 {count} 个时间点目录。",
        "Read the catalog for {count} timepoints in the bound Session.",
    ),
    "timepoint_inspector_inspected": (
        "已读取 {count} 个时间点的已保存状态。",
        "Read the saved state of {count} timepoints.",
    ),
    "timepoint_inspector_limits": (
        "此次查询未重新计算或修改数据；未独立核验剂量结果是否仍与当前输入一致，也不确认临床可用性。",
        "This query did not recompute or change data. It did not independently verify dose freshness against current inputs or establish clinical readiness.",
    ),
    "legacy_default_requires_runtime_migration": (
        "默认时间点的删除需要先完成运行时范围迁移。",
        "Deleting the default timepoint requires runtime scope migration first.",
    ),
    "timepoint_operation_failed": (
        "已保存的任务记录显示操作失败；该记录不能证明临床计算已完成。",
        "The saved task record reports an operation failure; it does not establish completed clinical computation.",
    ),
    "timepoint_operation_saved": (
        "这是已保存的任务状态，尚未在本次查询中核验。",
        "This is a saved task state, not independently verified by this query.",
    ),
    "timepoint_method_not_allowed": (
        "此时间点接口不支持该请求方法。",
        "This request method is not supported by the timepoint endpoint.",
    ),
    "rate_limit_exceeded": (
        "请求过于频繁，请等待后重试。",
        "Too many requests. Wait before retrying.",
    ),
    "timepoint_request_failed": (
        "时间点请求未能完成，请检查服务端记录；本响应不确认操作结果。",
        "The timepoint request could not be completed. Check the server records; this response does not confirm the operation's outcome.",
    ),
}


def supported_language(value):
    """Reuse locale normalization, but accept only bounded zh/en values."""
    if not isinstance(value, str) or not _LOCALE.fullmatch(value.strip()):
        return ""
    normalized = normalize_language(value, default="")
    return normalized if normalized in SUPPORTED_LANGUAGES else ""


def resolve_timepoint_language(*, language=None, agent=None, user=None, default="en"):
    """Read the already-selected shared language, without a text heuristic.

    Scoped runtime callers can supply their captured language explicitly. The
    shared memory's current user_lang wins over its older session fallback.
    This does not update memory, call get_agent, or decode workspace arrays.
    """
    explicit = supported_language(language)
    if explicit:
        return explicit
    memory = getattr(agent, "memory", None)
    selected = supported_language(getattr(memory, "user_lang", None))
    if selected:
        return selected
    if memory is not None and callable(getattr(memory, "retrieve", None)):
        try:
            previous = memory.retrieve("session_language")
        except Exception:
            previous = None
        selected = supported_language(previous.get("code")) if isinstance(previous, Mapping) else ""
        if selected:
            return selected
    if isinstance(user, Mapping):
        for key in ("user_lang", "language"):
            selected = supported_language(user.get(key))
            if selected:
                return selected
    return supported_language(default) or "en"


def request_timepoint_language(*, user=None, session_id=None):
    """Use an explicit header or a request agent with matching owner/Session."""
    from flask import g, has_request_context, request

    if not has_request_context():
        return resolve_timepoint_language(user=user)
    agent = None
    bound = getattr(g, "brachybot_workspace", None)
    if (isinstance(user, Mapping) and session_id is not None
            and isinstance(bound, (tuple, list)) and len(bound) == 2
            and str(bound[0]) == str(user.get("id")) and str(bound[1]) == str(session_id)):
        agent = getattr(g, "brachybot_agent", None)
    return resolve_timepoint_language(language=request.headers.get(LANGUAGE_HEADER), agent=agent, user=user)


def _safe_code(code, fallback="timepoint_request_failed"):
    return code if isinstance(code, str) and _CODE.fullmatch(code) else fallback


def timepoint_message(code, language=None, *, message_code=None, count=None):
    """Reusable structured code -> public presentation for routes and runtimes.

    Unknown technical codes remain stable, with a fixed generic message. No
    error text is accepted as a template, parameter, or language hint.
    """
    code = _safe_code(code)
    key = message_code if message_code in _MESSAGES else code
    key = key if key in _MESSAGES else "timepoint_request_failed"
    lang = resolve_timepoint_language(language=language)
    params = {}
    if "{count}" in _MESSAGES[key][0]:
        if type(count) is not int or not 0 <= count <= 256:
            raise ValueError("Public timepoint counts must be integers from 0 to 256")
        params["count"] = count
    template = _MESSAGES[key][0 if lang == "zh" else 1]
    return {"code": code, "message_code": key, "language": lang,
            "message": template.format(**params), "message_params": params}


class TimepointMessageError(ValueError):
    """A public input condition expressed by a code, never raw server text."""

    def __init__(self, code, *, message_code=None):
        self.code = _safe_code(code)
        self.message_code = message_code
        super().__init__(self.code)


def timepoint_error(exc, language=None):
    """Return (safe payload, HTTP status), classified without str(exception)."""
    from web.timepoints import (
        TimepointConflict, TimepointDependencyConflict, TimepointError,
        TimepointIntegrityError, TimepointNotFound,
    )
    from web.workspace_store import (
        WorkspaceArchived, WorkspaceError, WorkspaceIntegrityError,
        WorkspaceLeaseConflict, WorkspaceNotFound,
    )

    detail = None
    dependents = None
    if isinstance(exc, (WorkspaceNotFound, TimepointNotFound)):
        code, status = "timepoint_not_found", 404
    elif isinstance(exc, TimepointDependencyConflict):
        code, status = _safe_code(exc.code), 409
        dependents = [value for value in exc.dependents if isinstance(value, str) and _IDENTIFIER.fullmatch(value)][:256]
    elif isinstance(exc, WorkspaceLeaseConflict):
        code, status, detail = "workspace_conflict", 409, "workspace_lease_conflict"
    elif isinstance(exc, WorkspaceArchived):
        code, status, detail = "workspace_conflict", 409, "workspace_archived"
    elif isinstance(exc, TimepointConflict):
        code, status = _safe_code(exc.code), 409
    elif isinstance(exc, (TimepointIntegrityError, WorkspaceIntegrityError)):
        code, status = "timepoint_integrity_error", 503
    elif isinstance(exc, TimepointMessageError):
        code, status, detail = exc.code, 400, exc.message_code
    elif isinstance(exc, TimepointError):
        code, status = _safe_code(exc.code), 400
    elif isinstance(exc, (WorkspaceError, TypeError, ValueError)):
        code, status = _safe_code(getattr(exc, "code", None), "invalid_workspace_request"), 400
    else:
        code, status = "timepoint_request_failed", 500
    packet = timepoint_message(code, language, message_code=detail)
    payload = {"success": False, **packet, "error": packet["message"]}
    if dependents is not None:
        payload["dependents"] = dependents
    return payload, status


def timepoint_http_error(status, language=None, *, code=None, message_code=None):
    """Localize auth/API middleware responses without parsing their text."""
    fallback = {400: "invalid_workspace_request", 401: "authentication_required", 403: "access_denied",
                404: "timepoint_not_found", 405: "timepoint_method_not_allowed", 409: "workspace_conflict",
                429: "rate_limit_exceeded", 503: "timepoint_integrity_error"}.get(status, "timepoint_request_failed")
    packet = timepoint_message(_safe_code(code, fallback), language, message_code=message_code)
    return {"success": False, **packet, "error": packet["message"]}


def timepoint_operation_presentation(operation, language=None):
    """Preserve saved task IDs/state, replace operational free-form messages.

    Raw exception diagnostics may occur in saved operation records. They are
    omitted from this read-only presentation, while custom titles and stable
    technical fields are not translated or reinterpreted.
    """
    if not isinstance(operation, Mapping):
        return {}
    result = deepcopy(dict(operation))
    diagnostics = {"error", "message", "detail", "details", "exception", "traceback", "error_details"}
    had_text = bool(diagnostics.intersection(result))
    failed = bool(result.get("error")) or result.get("state") == "failed" or result.get("status") == "failed"
    for key in diagnostics:
        result.pop(key, None)
    if had_text or failed:
        packet = timepoint_message(result.get("code") or result.get("error_code") or (
            "timepoint_operation_failed" if failed else "timepoint_operation_saved"), language)
        result["presentation"] = packet
        result["message"] = packet["message"]
        if failed:
            result["error"] = packet["message"]
    return result
