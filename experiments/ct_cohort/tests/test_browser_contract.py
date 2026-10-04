"""Actual Chromium controls against a synthetic HTTP application, NOT a SUT result."""
import base64
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from brachycohort.browser import Browser
from brachycohort.core import Journal, atomic_json
from brachycohort.observer import verify_effective_target
from brachycohort.preflight import preflight
from brachycohort.runner import fingerprint


HTML = '''<!doctype html><html><body>
<div id="authOverlay" hidden></div><button class="new-chat-btn" onclick="newCase()">New</button>
<button data-panel="input">Input</button><button data-panel="viewers">Viewers</button><button data-panel="report">Report</button>
<input id="fileCT" type="file"><input id="fileCTV" type="file"><div id="tree"></div><div id="sessions"><div class="session-item" oncontextmenu="event.preventDefault();showExport()"><div><div id="session-title-synthetic_case">Case</div></div></div></div>
<div aria-controls="hyperparamsSection" onclick="document.getElementById('hyperparamsSection').style.display='block'">Settings</div>
<div id="hyperparamsSection" style="display:none">
<input id="inLowestEnergy" type="number"><input id="outHighestEnergy" type="number"><input id="dvhRate" type="number"><input id="maxIter" type="number">
<label><input id="useRLToggle" type="checkbox">RL</label><button onclick="applyHyperparams()">Apply</button></div>
<textarea id="chatInput"></textarea><button id="chatSendBtn" onclick="chat()">Send</button>
<button onclick="runPlanning()">Plan</button><button id="generateSurgicalGuideButton" onclick="generateGuide()">Guide</button>
<button onclick="Report.autoFill.fromAll()">Report</button><button onclick="Report.export.pdf()">PDF</button>
<span id="reportStatusText">Ready</span>
<script>
var state={ctLoaded:false,isProcessing:false};
async function post(path,data){return (await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})})).json();}
async function newCase(){await post('/api/sessions');document.getElementById('sessions').innerHTML='<div class="session-item" oncontextmenu="event.preventDefault();showExport()"><div><div id="session-title-synthetic_case">Case</div></div></div>';}
document.getElementById('fileCT').onchange=async()=>{await post('/api/upload');state.ctLoaded=true;};
document.getElementById('fileCTV').onchange=async()=>{await post('/api/segmentation');document.getElementById('tree').innerHTML='<div class="tree-item" data-node-id="mask_test" oncontextmenu="event.preventDefault();showMove()">Mask</div>';};
function showMove(){let d=document.createElement('div');d.className='ctx-menu-item';d.textContent='Move to CTV';d.setAttribute('onclick',"moveSelectedMasks('ctv')");document.getElementById('tree').appendChild(d);}
async function moveSelectedMasks(x){await fetch('/api/data/generic-masks/classification',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({object_ids:['mask:test'],classification:x})});}
async function applyHyperparams(){await post('/api/config');}
async function chat(){await post('/api/chat',{message:document.getElementById('chatInput').value});}
async function runPlanning(){await post('/api/planning/run_step');}
async function generateGuide(){await post('/api/surgical-guides/generate');}
var Report={autoFill:{fromAll:async()=>{await post('/api/report/auto-fill');document.getElementById('reportStatusText').className='ok';}},export:{pdf:()=>download('/pdf')}};
function download(path){let a=document.createElement('a');a.href=path;a.download='result';document.body.appendChild(a);a.click();a.remove();}
function showExport(){document.body.insertAdjacentHTML('beforeend','<button data-session-export onclick="exportMenu()">Export</button>');}
function exportMenu(){let a=document.createElement('button');a.setAttribute('data-export-all','');a.textContent='All';document.body.appendChild(a);let b=document.createElement('button');b.setAttribute('data-export-start','');b.textContent='Export';b.onclick=()=>download('/zip');document.body.appendChild(b);}
</script></body></html>'''


@pytest.fixture
def web_fixture(storage, make_pair, tmp_path):
    labels = np.zeros((4, 5, 6), dtype=np.uint8)
    labels[1:3, 2, 3] = 1
    row = preflight(make_pair(labels, [1]), storage, {})
    assert row["preflight_status"] == "PASS"
    runtime = tmp_path / "metadata"
    root = runtime / "workspaces/test_user/synthetic_case"
    root.mkdir(parents=True)
    seen, flags = [], {"ct": False, "staged": False, "promoted": False, "task": False}
    image = sitk.ReadImage(row["derived_label_path"])
    array = sitk.GetArrayFromImage(image)
    state = {"ct_spacing": image.GetSpacing(), "ct_origin": image.GetOrigin(), "ct_direction": image.GetDirection()}
    def snapshot():
        atomic_json(root / "snapshot.json", {"session_id": "synthetic_case", "agent": {"planning_results": state}, "operation": {"state": "ready"}})
    snapshot()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, data, content="application/json", attachment=None):
            data = json.dumps(data).encode() if content == "application/json" else data
            self.send_response(200)
            self.send_header("Content-Type", content)
            if attachment:
                self.send_header("Content-Disposition", 'attachment; filename="' + attachment + '"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.command, self.path, body))
            if self.path == "/api/sessions":
                self.reply({"success": True, "active_session_id": "synthetic_case"})
            else:
                flags[{"/api/upload": "ct", "/api/segmentation": "staged", "/api/chat": "task"}.get(self.path, "other")] = True
                self.reply({"success": True})
        def do_PATCH(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.command, self.path, body))
            flags["promoted"] = True
            state.update(ctv_source_object_ids=["mask:test"], ctv_binary_array={"$ndarray_inline": base64.b64encode(array.tobytes()).decode(), "dtype": "uint8", "shape": list(array.shape)})
            snapshot()
            self.reply({"success": True, "object_ids": ["mask:test"]})
        def do_GET(self):
            seen.append((self.command, self.path, b""))
            if self.path == "/":
                self.reply(HTML.encode(), "text/html")
            elif self.path == "/api/data/catalog":
                objects = []
                if flags["ct"]:
                    objects.append({"object_id": "image:ct", "data_type": "image"})
                if flags["staged"]:
                    objects.append({"object_id": "mask:test", "data_type": "generic_mask", "metadata": {"data_tree_node_id": "mask_test", "voxel_count": row["target_voxels"]}})
                self.reply({"session_id": "synthetic_case", "objects": objects})
            elif self.path == "/api/chat/task":
                self.reply({"task": {"task_id": "test_task", "session_id": "synthetic_case", "status": "completed"} if flags["task"] else None})
            elif self.path == "/api/workspace/snapshot":
                self.reply({"workspace": {"session_id": "synthetic_case", "operation": {"state": "ready"}}})
            elif self.path == "/api/planning/results":
                state.update(planning_id="p1", plan_config={"effective_mode": "rl"},
                    planning_provenance={"input_paths": {"ctv_effective": {"object_ids": ["mask:test"], "mask": {"sha256": fingerprint(array)}}},
                        "parameters": {"in_lowest_dose_gy": 42, "out_highest_dose_gy": 84, "DVH_rate": .8, "max_iter": 2}, "mode": "rl"})
                snapshot()
                self.reply({"planning_id": "p1", "planning_data_version": 1,
                    "seeds": [{"id": "s1", "pos": [1, 2, 3], "trajectory_id": "t1"}],
                    "needles": [{"id": "n1", "entry": [1, 2, 3], "tip": [4, 5, 6]}],
                    "has_dose": True, "has_dvh": True, "has_guide": True, "dvh": {"synthetic": [1]},
                    "metrics": {"v100": 80, "oar_metrics": {"test_organ": {"d2cc": 1}}}})
            elif self.path == "/pdf":
                from pypdf import PdfWriter
                from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
                b = io.BytesIO()
                w = PdfWriter()
                page = w.add_blank_page(width=100, height=100)
                font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
                page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
                stream = DecodedStreamObject()
                stream.set_data(b"BT /F1 10 Tf 10 10 Td (Synthetic report only) Tj ET")
                page[NameObject("/Contents")] = w._add_object(stream)
                w.write(b)
                self.reply(b.getvalue(), "application/pdf", "report.pdf")
            elif self.path == "/zip":
                import trimesh
                b = io.BytesIO()
                dose = sitk.GetImageFromArray(np.full(array.shape, 10, dtype=np.float32))
                dose.CopyInformation(image)
                dose_path = tmp_path / "dose-export.nii.gz"
                sitk.WriteImage(dose, str(dose_path))
                with zipfile.ZipFile(b, "w") as z:
                    z.write(dose_path, "Session/dose.nii.gz")
                    z.writestr("Session/guide.stl", trimesh.creation.box().export(file_type="stl"))
                    z.writestr("Session/session_manifest.json", json.dumps({"session_id": "synthetic_case", "planning_id": "p1", "data_version": 1,
                        "files": [{"data_type": "dose", "relative_path": "dose.nii.gz"}, {"data_type": "surgical_guide", "relative_path": "guide.stl"}]}))
                self.reply(b.getvalue(), "application/zip", "session.zip")
            else:
                self.reply({"success": True})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {"deployment_url": f"http://127.0.0.1:{server.server_port}", "headless": True,
           "metadata_runtime": str(runtime), "browser_tmpfs": "/dev/shm",
           "budgets": {"upload_s": 15, "workflow_s": 15, "guide_s": 15, "report_s": 15, "export_s": 15}}
    yield row, cfg, seen, flags
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("arm", ["browser-chat", "manual-ui"])
async def test_actual_browser_contract(storage, tmp_path, web_fixture, approved_profile, arm):
    row, cfg, seen, flags = web_fixture
    root = tmp_path / arm
    root.mkdir()
    journal = Journal(root)
    async with Browser(cfg, storage, journal, root) as driver:
        await driver.create_case()
        assert (root / "session.json").is_file()  # durable before caller/upload
        with pytest.raises(Exception, match="CTV_PROVENANCE_MISMATCH"):
            verify_effective_target(cfg["metadata_runtime"], "synthetic_case", row, ["mask:test"])
        selected, evidence = await driver.upload_and_promote(row)
        assert evidence["status"] == "PASS" and selected == ["mask:test"]
        await driver.apply_profile(approved_profile)
        if arm == "browser-chat":
            await driver.chat("Synthetic tool-scheduling test; no clinical data")
            assert (root / "chat_task.json").is_file()
            await driver.wait_chat()
        else:
            await driver.manual_ui()
        assert (await driver.export_pdf()).is_file()
        assert (await driver.export_session()).is_file()
    mutation_paths = [path for method, path, _ in seen if method != "GET"]
    assert mutation_paths.index("/api/segmentation") < mutation_paths.index("/api/data/generic-masks/classification")
    assert mutation_paths.index("/api/data/generic-masks/classification") < mutation_paths.index("/api/config")
    assert ("/api/chat" in mutation_paths) == (arm == "browser-chat")
    assert ("/api/planning/run_step" in mutation_paths) == (arm == "manual-ui")


async def test_disconnected_runner_collects_existing_case_without_resubmission(storage, web_fixture, approved_profile, monkeypatch):
    from brachycohort.core import digest, load_json
    from brachycohort.recovery import recover_case
    from brachycohort.progress import settlement
    row, cfg, seen, flags = web_fixture
    cfg.update(per_case_max_export_bytes=10000000, minimum_pdf_pages=1)
    cfg["budgets"]["overall_s"] = 90
    rec = {"synthetic": "case-level-interruption"}
    rh = digest(rec)
    root = storage.path("runs/" + rh + "/first")
    atomic_json(root / "attempt.json", {"recipe_hash": rh, "recipe": {"arm": "browser-chat"},
                "row": {**row, "inference_cluster_id": "synthetic"}, "profile": approved_profile,
                "resumability_version": 1})
    async with Browser(cfg, storage, Journal(root), root) as driver:
        await driver.create_case()
        selected, evidence = await driver.upload_and_promote(row)
        atomic_json(root / "selected_target.json", {"object_ids": selected, "evidence": evidence})
        await driver.apply_profile(approved_profile)
        await driver.chat("Synthetic interrupted case; no clinical data")
        # Simulate a lost runner after submission, before wait/export/terminal commit.
    before = [v for v in seen if v[0] != "GET"]
    monkeypatch.setattr("brachycohort.runtime.validate_live_service", lambda *_a, **_k: None)
    result = await recover_case(root, cfg, storage, {"acceptance_rules": {"guide_checks": [], "report_checks": []}})
    assert result["state"] == "SETTLED" and result["collection_finished"]
    assert result["primary_first_attempt_success_changed"] is False
    assert [v for v in seen if v[0] != "GET"] == before
    assert settlement(root)["state"] == "SETTLED"
    assert load_json(root / "terminal_result.json")["workflow_completion"] == "UNKNOWN"
    assert (Path(result["destination"]) / "report.pdf").is_file()


@pytest.mark.parametrize("arm", ["browser-chat", "manual-ui"])
async def test_whole_attempt_keeps_unknown_review_out_of_success(storage, web_fixture, approved_profile, arm, monkeypatch):
    from brachycohort.runner import attempt
    from brachycohort.core import digest, load_json
    import brachycohort.resources as resources
    async def quiet_sampler(journal, stop):
        await stop.wait()
    monkeypatch.setattr(resources, "sample", quiet_sampler)
    row, cfg, seen, flags = web_fixture
    row["inference_cluster_id"] = "synthetic-cluster"
    row.update(clinical_eligibility="APPROVED_RESEARCH", planning_profile_id=approved_profile["id"])
    cfg.update(product_revision="synthetic-code-revision", experiment_id="synthetic", random_seed=1)
    cfg["budgets"]["overall_s"] = 90
    result = await attempt(cfg, storage, row, approved_profile, digest(approved_profile), arm,
                           {"hash": "synthetic-protocol", "acceptance_rules": {"guide_checks": ["wall"], "report_checks": ["readability"]}})
    assert result["workflow_completion"] == "UNKNOWN", result
    assert result["checks"]["consumed_recipe"]["status"] == "PASS"
    assert result["checks"]["guide_mesh"]["status"] == "PASS"
    assert result["checks"]["pdf"]["status"] == "PASS"
    root = storage.path("runs/" + result["recipe_hash"] + "/" + result["attempt_id"])
    assert load_json(root / "terminal_result.json")["status"] == "PARTIAL_OR_UNEVALUABLE"
    assert (root / "oar_metrics.json").is_file() and (root / "plan_geometry.json").is_file()
    assert any(v.get("data_type") == "surgical_guide" for v in load_json(root / "artifact_manifest.json"))
