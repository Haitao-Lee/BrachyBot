"""Read actual owned dose components; never substitute another source set."""
import hashlib
import json

import numpy as np
from flask import Response, jsonify, request

from utils.dose_units import physical_volume, workspace_physical_dose
from web.server_support import require_api_key
from web.timepoint_http import current_binding
from web.timepoint_messages import request_timepoint_language, timepoint_error
from web.timepoints import TimepointConflict, TimepointError
from web.workspace_store import WorkspaceError


def dose_view_packet(agent, source_set, *, evaluate_component=True):
    if source_set not in {"implanted", "planned", "total"}:
        raise TimepointError("Select implanted, planned or total dose explicitly")
    retrieve = agent.memory.retrieve
    context = agent._workspace_timepoint_context
    packet = {"success": True, "session_id": context.session_id, "timepoint_id": context.target.timepoint_id,
        "source_set": source_set, "available": False, "stale": False, "dose_units": "gy"}
    bundle = retrieve("dose_components") or {}
    record = bundle.get(source_set) if isinstance(bundle, dict) else None
    if source_set == "implanted" and not record:
        record = retrieve("implanted_dose_record")
    if record:
        from web.timepoint_resources import fingerprint
        if record.get("dose_units") != "physical_gy":
            raise TimepointConflict("A saved component has no explicit physical dose units")
        dose = physical_volume(record["dose_distribution_physical_gy"], units="physical_gy")
        packet["stale"] = record.get("status") == "stale" or record.get("dose_status") == "stale"
        if record.get("dose_sha256") != fingerprint(dose):
            raise TimepointConflict("The saved dose content no longer matches its receipt")
        resources = retrieve("timepoint_resource_state") or {}
        if (resources.get("fingerprints") or {}).get(source_set + "_dose") != record.get("dependency_fingerprint"):
            packet["stale"] = True
        packet.update(shape=list(dose.shape), spacing=record.get("ct_spacing") or retrieve("ct_spacing"),
            origin=record.get("ct_origin") or retrieve("ct_origin"),
            direction=record.get("ct_direction") or retrieve("ct_direction"),
            geometry_signature=record.get("grid_signature"), dose_sha256=record["dose_sha256"],
            source_count=record.get("source_count"), dose_basis=record.get("dose_basis"))
    else:
        # Ordinary historical preoperative plans have one source set. This
        # compatibility read is not allowed for an intraoperative workspace.
        if context.target.stage == "intraoperative" or source_set == "implanted" or retrieve("implanted_seed_reconstruction"):
            packet["stale"] = bool(retrieve("dose_metrics") or retrieve("dose_distribution"))
            return packet, None
        try:
            dose = workspace_physical_dose(retrieve)
        except ValueError:
            packet["stale"] = True
            return packet, None
        if dose is None:
            return packet, None
        dose = np.asarray(dose)
        grid = {"shape": list(dose.shape), "spacing": retrieve("ct_spacing"),
                "origin": retrieve("ct_origin"), "direction": retrieve("ct_direction")}
        packet.update(**grid, source_count=retrieve("total_seeds"),
            dose_basis="projected_total_source_dose_not_elapsed_delivered_dose",
            geometry_signature=hashlib.sha256(json.dumps(grid, sort_keys=True).encode()).hexdigest())
    from web.planning_runs import current_planning_context
    from utils.resource_status import resource_is_stale
    artifacts=retrieve('manual_artifact_status') or retrieve('artifact_status') or {}
    if source_set in {'planned','total'} and resource_is_stale(artifacts.get('dose')):
        # Legacy manual edit entrypoints invalidate aliases/status before the
        # next source-fingerprint rebuild. Do not export or paint an untouched
        # old supplemental/total record as current in that interval. Implanted
        # source geometry is independent of a future-plan edit.
        packet['stale']=True
    packet.update(available=True, planning_id=current_planning_context(agent.memory)['planning_id'],
        dose_generation=(retrieve("timepoint_resource_state") or {}).get("fingerprints", {}).get(source_set + "_dose"),
        clinical_use_ready=False)
    if source_set == "total" or not bundle:
        packet.update(metrics=current_planning_context(agent.memory)['metrics'] if not packet['stale'] else {},
            dvh=retrieve("dvh_data") or {} if not packet['stale'] else {})
    elif evaluate_component:
        # Show measured component DVH without calling it the overall plan score.
        from utils.ctv_targets import resolve_ctv_target
        mask = resolve_ctv_target(retrieve)
        if mask is not None and retrieve('oar_array') is not None:
            from web.dose_components import evaluate_total
            from web.planning_config import current_evaluation_config
            component = {"dose_distribution_physical_gy": dose,
                "dose_sha256": packet.get("dose_sha256", "component-display"),
                'dose_units':'physical_gy','grid_signature':record['grid_signature']}
            result = evaluate_total({"total": component}, mask, retrieve("oar_array"), retrieve("ct_image"),
                current_evaluation_config(retrieve), organ_names=retrieve("organ_names"))
            values = result["metrics"]
            packet["metrics"] = {key.lower(): value for key, value in values["CTV"].items() if key != "dvh"}
            packet["metrics"].update(source_set=source_set, component_only=True,
                oar_metrics={name: {key.lower(): value for key, value in row.items() if key != "dvh"}
                             for name, row in values.items() if name != "CTV"})
            packet["dvh"] = {name: row["dvh"] for name, row in values.items() if "dvh" in row}
        else:
            packet.update(metrics={}, dvh={})
    return packet, dose


def register_dose_component_routes(app, get_agent):
    @app.post('/api/dose/recompute')
    @require_api_key
    def dose_component_recompute():
        try:
            binding = current_binding()
            if binding is None:
                raise TimepointError('An owned target binding is required for dose recomputation')
            data = request.get_json(silent=True)
            if (not isinstance(data,dict) or set(data)-{'source_set','expected_clinical_revision','expected_observation_revision_id'}
                    or not isinstance(data.get('source_set'),str)
                    or data.get('source_set') not in {'implanted','planned','both','total'}
                    or type(data.get('expected_clinical_revision')) is not int
                    or data.get('expected_clinical_revision',-1)<0
                    or ('expected_observation_revision_id' in data and
                        not isinstance(data['expected_observation_revision_id'],str))):
                raise TimepointError('Use a versioned explicit source-set dose request')
            agent = get_agent()
            store = getattr(agent._workspace_store,'raw',agent._workspace_store)
            store.assert_editable(binding.owner_id,binding.session_id,request.headers.get('X-BrachyBot-Editor',''))
            context = agent._workspace_timepoint_context
            if context.target.clinical_revision != data['expected_clinical_revision']:
                raise TimepointConflict('The requested dose inputs changed')
            if data['source_set'] in {'implanted','both','total'} and not data.get('expected_observation_revision_id'):
                raise TimepointError('Capture the current observation revision before computing its dose')
            from tool_factory.dose_recompute import CurrentPlanDoseRecomputeTool
            result = CurrentPlanDoseRecomputeTool().execute(_agent=agent,source_set=data['source_set'],
                expected_observation_revision_id=data.get('expected_observation_revision_id'))
            if not result.success:
                from web.timepoint_messages import timepoint_message
                packet = timepoint_message((result.metadata or {}).get('code','component_dose_recompute_failed'),request_timepoint_language())
                return jsonify(success=False,error=packet['message'],**packet),409
            # A result acknowledgement precedes neither the owned numerical
            # commit nor its stale-input read-set check.
            runtime = getattr(agent,'_workspace_scoped_http_runtime',None)
            if runtime is not None:
                runtime.checkpoint()
            return jsonify(success=True,session_id=binding.session_id,timepoint_id=binding.timepoint_id,
                source_set=data['source_set'],metadata=result.metadata,downstream_actions_executed=[])
        except (WorkspaceError,TimepointError,ValueError,KeyError) as exc:
            packet,status = timepoint_error(exc,request_timepoint_language())
            return jsonify(packet),status

    @app.get("/api/dose/view")
    @require_api_key
    def dose_component_view():
        try:
            agent = get_agent()
            packet, dose = dose_view_packet(agent, request.args.get("source_set", "total"))
            if dose is not None and not packet["stale"]:
                if dose.size <= 1_000_000:
                    packet["dose"] = dose.ravel().tolist()
                else:
                    packet["volume_url"] = "/api/dose/view-volume?source_set=" + packet["source_set"]
            return jsonify(packet)
        except (TimepointError, ValueError, KeyError) as exc:
            packet, status = timepoint_error(exc, request_timepoint_language())
            return jsonify(packet), status

    @app.get("/api/dose/view-volume")
    @require_api_key
    def dose_component_volume():
        try:
            packet, dose = dose_view_packet(get_agent(), request.args.get("source_set", "total"))
            if dose is None or packet["stale"]:
                return jsonify(success=False, code="dose_component_unavailable"), 409
            low, high = float(dose.min()), float(dose.max())
            scale = (high - low) / 65535 if high > low else 0.0
            quantized = np.rint((dose - low) / scale).astype("<u2") if scale else np.zeros(dose.shape, dtype="<u2")
            response = Response(quantized.tobytes(), mimetype="application/octet-stream")
            response.headers.update({"X-Dose-Min-Gy": str(low), "X-Dose-Quantization-Gy": str(scale),
                "X-Dose-Shape": json.dumps(packet["shape"]), "X-Dose-Source-Set": packet["source_set"],
                "X-BrachyBot-Session": packet["session_id"], "X-BrachyBot-Timepoint": packet["timepoint_id"],
                "X-Dose-SHA256": str(packet.get("dose_sha256") or ""), "Cache-Control": "private, no-store"})
            return response
        except (TimepointError, ValueError, KeyError) as exc:
            packet, status = timepoint_error(exc, request_timepoint_language())
            return jsonify(packet), status
