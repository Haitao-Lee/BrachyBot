"""Construction/negative-control tests only. Never calls a model or SUT."""
import copy
import io
import json
import math
import os
from pathlib import Path
import random
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(os.environ.get("PUBLIC_COLLECTION_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT.parent))
from public_collection.collect import confined, fetch, read_json, sha256, unpack, verify, write_json
from public_collection.pool import ProtocolBlocked, PublicPool, export_public


@pytest.fixture(scope="module")
def pools():
    return {e["id"]: PublicPool(e["id"], ROOT) for e in read_json(ROOT / "catalog.json")["benchmarks"]}


def test_integrity_and_no_result_claim():
    result = verify(ROOT)
    assert result["problems"] == []
    assert result["sut_runs"] == 0
    assert "not_sut_evaluation" in result["evaluation_mode"]


COUNTS = {"EXT-16": 3952, "EXT-17": 3472, "EXT-18": 4450, "EXT-19": 74,
          "EXT-20": 597, "EXT-21": 41816, "EXT-22": 3680, "EXT-23": 511,
          "EXT-24": 323, "EXT-25": 300, "EXT-26": 400, "EXT-27": 2108}
FIELDS = {"EXT-16": {"question", "tools", "candidates"}, "EXT-17": {"messages", "tools"},
          "EXT-18": {"question", "options", "image_refs"}, "EXT-19": {"messages"},
          "EXT-20": {"clinical_text", "sentences"}, "EXT-21": {"question", "options", "student_answer", "input"},
          "EXT-22": {"question", "options"}, "EXT-23": {"query", "corpus_id"},
          "EXT-24": {"query", "corpus_id"}, "EXT-25": {"query", "corpus_id"},
          "EXT-26": {"documents", "question", "options"}, "EXT-27": {"tools", "messages"}}


@pytest.mark.parametrize("ext_id", list(COUNTS))
def test_every_task_public_boundary_and_unique_ids(pools, ext_id):
    pool = pools[ext_id]
    ids = pool.list_tasks()
    assert len(ids) == COUNTS[ext_id] == len(set(ids))
    for tid in ids:
        task = pool.task(tid)
        assert task.private and task.public and task.cluster
        assert set(task.public) <= FIELDS[ext_id]
        assert "reference_answer" not in task.public and "label" not in task.public
        # Poison every private object. Input must be a task-owned projection,
        # not something constructed from a gold field at invocation time.
        before = json.dumps(task.public, ensure_ascii=False)
        task.private["audit_private_canary"] = "DO_NOT_EXPOSE_GOLD_8371"
        assert "DO_NOT_EXPOSE_GOLD_8371" not in before
        if ext_id != "EXT-22":
            out = pool.build_input(tid)
            assert json.dumps(out, ensure_ascii=False) == before
            out["caller_mutation"] = True
            assert "caller_mutation" not in pool.task(tid).public
    summary = pool.summary()
    assert summary["sut_runs"] == 0 and not summary["protocol_fidelity_certified"]


def test_bfcl_orphan_not_repaired_by_order(pools):
    pool = pools["EXT-17"]
    pool.list_tasks()
    assert len(pool.blocked_source_ids) == 1
    assert pool.blocked_source_ids[0]["id"] == "live_multiple_1052-79-0"
    assert not any(t.source_id == "live_multiple_1052-79-0" for t in pool._tasks.values())


def test_upstream_bfcl_positive_wrong_tool_and_irrelevance(pools):
    pool = pools["EXT-17"]
    tid = next(tid for tid in pool.list_tasks() if pool.task(tid).subset == "simple")
    gold = pool.task(tid).private["ground_truth"]
    calls = [{name: {key: value[0] for key, value in params.items()}}
             for call in gold for name, params in call.items()]
    assert pool.score_bfcl(tid, calls)["valid"]
    assert not pool.score_bfcl(tid, [{"nonexistent_function": {}}])["valid"]
    tid = next(tid for tid in pool.list_tasks() if pool.task(tid).subset == "irrelevance")
    assert pool.score_bfcl(tid, [])["upstream_irrelevance_accuracy"] == 1
    assert pool.score_bfcl(tid, [{"nonexistent_function": {}}])["upstream_irrelevance_accuracy"] == 0


def test_when2call_original_prompt_does_not_return_target(pools):
    pool = pools["EXT-16"]
    tid = next(t for t in pool.list_tasks() if pool.task(t).subset == "mcq")
    obs = pool.when2call_prompt(tid)
    assert set(obs) == {"prompt", "candidates"}
    assert len(obs["candidates"]) == 4 and pool.task(tid).public["question"] in obs["prompt"]
    judge = next(t for t in pool.list_tasks() if pool.task(t).subset == "llm_judge")
    with pytest.raises(ProtocolBlocked):
        pool.when2call_prompt(judge)
    assert pool.summary()["clusters"] == 1295


def test_cmb_case_history_no_teacher_forcing(pools):
    pool = pools["EXT-19"]
    assert pool.summary()["user_turns"] == 208
    tid = next(t for t in pool.list_tasks() if len(pool.task(t).private["user_turns"]) > 1)
    assert len(pool.build_input(tid)["messages"]) == 1
    assert set(pool.build_input(tid)) == {"messages"}  # no future-turn schedule
    result = pool.cmb_messages(tid, ["MY_PREVIOUS_MODEL_OUTPUT_761"])
    assert [m["role"] for m in result] == ["user", "assistant", "user"]
    assert result[1]["content"] == "MY_PREVIOUS_MODEL_OUTPUT_761"
    assert pool.task(tid).private["answers"][0] != result[1]["content"]
    with pytest.raises(ValueError):
        pool.cmb_messages(tid, [""] * len(pool.task(tid).private["user_turns"]))


def test_medec_and_medhalt_split_selection(pools):
    assert pools["EXT-20"].summary()["exclusions"]["upstream_blank_rows"] == 328
    pool = pools["EXT-21"]
    for t in pool._load().values():
        if t.subset.startswith("reasoning"):
            assert t.private["split_type"] == "test"
            assert t.subset != "reasoning_fake"
        else:
            assert set(t.public) == {"input"}
    assert pool.summary()["exclusions"]["reasoning_fake_non_test"] == 1858
    assert pool.summary()["clusters"] < COUNTS["EXT-21"]


def test_medrgb_no_invented_rag_protocol(pools, tmp_path):
    pool = pools["EXT-22"]
    with pytest.raises(ProtocolBlocked):
        pool.build_input(pool.list_tasks()[0])
    with pytest.raises(ProtocolBlocked):
        export_public(pool, tmp_path / "no_fake_rag")
    assert not (tmp_path / "no_fake_rag").exists()


def test_medx_all_test_images_present_and_native_score(pools):
    pool = pools["EXT-18"]
    names = set()
    with zipfile.ZipFile(pool.folder / "data/images.zip") as archive:
        members = set(archive.namelist())
        for t in pool._load().values():
            if t.subset == "MM":
                assert t.private["images"]
                for name in t.private["images"]:
                    assert "images/" + name in members
                    names.add(name)
    assert len(names) == 2852
    ids = pool.list_tasks()
    for tid in ids[:15]:
        label = pool.task(tid).private["label"]
        assert pool.score_medxpert(tid, "The answer is " + label)["upstream_accuracy"] == 1
        # English pronoun 'I' is itself a valid A-J choice in the upstream
        # parser. A negative control must be an actually different choice;
        # don't weaken or silently replace the upstream implementation.
        wrong = next(c for c in pool.task(tid).public["options"] if c != label)
        assert pool.score_medxpert(tid, "The answer is " + wrong)["upstream_accuracy"] == 0
        assert pool.score_medxpert(tid, "no valid selection")["upstream_accuracy"] == 0
    tid = next(t for t in ids if pool.task(t).subset == "MM")
    assert all(b for b in pool.image_bytes(tid))


def test_medx_upstream_abstention_parser_defect_is_disclosed(pools):
    pool = pools["EXT-18"]
    tid = next(t for t in pool.list_tasks() if pool.task(t).private["label"] == "I")
    # Reproduce the native defect rather than fixing its metric behind users'
    # backs. Formal comparisons must separately record raw abstentions.
    assert pool.score_medxpert(tid, "I cannot select an option.")["upstream_accuracy"] == 1


@pytest.mark.parametrize("ext_id,subset", [("EXT-23", "IIYi-Clinical"), ("EXT-24", "nfcorpus"), ("EXT-25", "scifact")])
def test_native_retrieval_negative_controls(pools, ext_id, subset):
    pool = pools[ext_id]
    tasks = {tid: t for tid, t in pool._load().items() if t.subset == subset}
    exact = {tid: {doc: float(score) for doc, score in t.private["qrels"].items() if score > 0}
             for tid, t in tasks.items()}
    positive = pool.score_retrieval(exact, subset)
    assert positive[0]["NDCG@10"] > .99
    negative = pool.score_retrieval({tid: {} for tid in tasks}, subset)
    assert negative[0]["NDCG@10"] == 0
    with pytest.raises(ValueError):
        pool.score_retrieval({}, subset)
    bad = copy.deepcopy(exact)
    first = next(iter(bad))
    bad[first] = {next(iter(tasks[first].private["qrels"])): math.nan}
    with pytest.raises(ValueError):
        pool.score_retrieval(bad, subset)


class TinyTokenizer:
    """Protocol unit-test stub, not a model tokenizer or context estimate."""
    def encode(self, text):
        return list(text)
    def decode(self, tokens):
        return "".join(tokens)


def test_longhealth_original_renderer_reproducibility_no_private_metadata(pools):
    pool = pools["EXT-26"]
    tid = pool.list_tasks()[0]
    before = random.getstate()
    a = pool.longhealth_prompt(tid, TinyTokenizer(), 100000, 41)
    b = pool.longhealth_prompt(tid, TinyTokenizer(), 100000, 41)
    assert a == b and random.getstate() == before
    assert set(a) == {"system", "prompt"}
    assert "answer_location" not in a["prompt"]
    assert pool.summary()["clusters"] == 20
    with pytest.raises(ValueError):
        pool.longhealth_prompt(tid, None, 16000, 41)


def test_injection_role_boundary_repeated_view_and_never_execute(pools):
    pool = pools["EXT-27"]
    assert pool.summary()["clusters"] == 1054
    for t in pool._load().values():
        assert [m["role"] for m in t.public["messages"]] == ["user", "assistant", "tool"]
        assert t.public["messages"][-1]["content"] == t.private["Tool Response"]
        assert not set(t.public).intersection({"Expected Achievements", "Attacker Instruction", "Thought", "Attack Type"})
        assert not any("attacker" in tool for tool in t.public["tools"])


def test_public_export_contains_no_gold_or_assets(pools, tmp_path):
    dest = tmp_path / "medec_public"
    export_public(pools["EXT-20"], dest)
    assert {p.name for p in dest.iterdir()} == {"inputs.jsonl", "PUBLIC_MANIFEST.json"}
    first = json.loads((dest / "inputs.jsonl").read_text().splitlines()[0])
    assert set(first["input"]) == FIELDS["EXT-20"]
    assert read_json(dest / "PUBLIC_MANIFEST.json")["no_gold"]
    with pytest.raises(FileExistsError):
        export_public(pools["EXT-20"], dest)


def test_mm_public_export_resolves_real_images(pools, tmp_path):
    source = pools["EXT-18"]
    tid = next(t for t in source.list_tasks() if source.task(t).subset == "MM")
    pool = PublicPool("EXT-18", ROOT)
    pool._tasks = {tid: source.task(tid)}
    dest = tmp_path / "mm-input"
    export_public(pool, dest)
    obs = json.loads((dest / "inputs.jsonl").read_text())["input"]
    assert len(obs["image_files"]) == len(obs["image_refs"]) > 0
    for record, original in zip(obs["image_files"], pool.image_bytes(tid), strict=True):
        assert (dest / record["path"]).read_bytes() == original
        assert record["mime_type"] in ("image/png", "image/jpeg")
    assert "label" not in obs


@pytest.mark.parametrize("path", ["../escape", "/abs", "a/../../x", "a\\bad", ""])
def test_confined_paths(path, tmp_path):
    with pytest.raises(ValueError):
        confined(tmp_path, path)


def test_archive_symlink_and_traversal_rejected(tmp_path):
    path = tmp_path / "bad.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("repo/data/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ValueError):
        unpack(path, tmp_path / "out", ["data"])
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/../../escape", "never leave collection")
    with pytest.raises(ValueError):
        unpack(path, tmp_path / "out", ["data"], kind="zip")


def test_modified_upstream_source_blocked(tmp_path):
    write_json(tmp_path / "catalog.json", {"benchmarks": [{"id": "EXT-18"}]})
    source = tmp_path / "assets/EXT-18/vendor/eval/utils.py"
    source.parent.mkdir(parents=True)
    source.write_text("raise AssertionError('must not import')")
    write_json(tmp_path / "assets.lock.json", {"files": {source.relative_to(tmp_path).as_posix(): {"sha256": "0" * 64}}})
    with pytest.raises(ProtocolBlocked):
        PublicPool("EXT-18", tmp_path)._module("vendor/eval/utils.py")


def test_fetch_must_not_erase_modified_locked_source(tmp_path):
    catalog = {"benchmarks": [{"id": "EXT-test", "source": "https://github.com/example/test",
        "revision": "a" * 40, "assets": [{"kind": "github", "paths": ["utils.py"]}]}]}
    write_json(tmp_path / "catalog.json", catalog)
    p = tmp_path / "assets/EXT-test/vendor/utils.py"
    p.parent.mkdir(parents=True)
    p.write_text("original")
    name = p.relative_to(tmp_path).as_posix()
    write_json(tmp_path / "assets.lock.json", {"catalog_sha256": sha256(tmp_path / "catalog.json"),
        "files": {name: {"sha256": sha256(p), "bytes": p.stat().st_size,
            "url": "https://raw.githubusercontent.com/example/test/" + "a" * 40 + "/utils.py",
            "download_url": "original_public_mirror_acquisition"}}})
    assert fetch(tmp_path) == []  # already cached: must not perform a download
    assert read_json(tmp_path / "assets.lock.json")["files"][name]["download_url"] == "original_public_mirror_acquisition"
    p.write_text("preserve my local edit")
    with pytest.raises(ValueError, match="preserve it"):
        fetch(tmp_path)
    assert p.read_text() == "preserve my local edit"


def test_legacy_direct_and_callback_input_boundaries():
    # import shared modified adapter_base from the overlay, not the live module
    from adapter_base import ExtAdapter, PUBLIC_INPUT_FIELDS, public_input
    for ext_id, fields in PUBLIC_INPUT_FIELDS.items():
        fake = {k: {"expected": "legitimate nested note"} for k in fields}
        fake.update(reference_answer="PRIVATE_A", reference_letter="PRIVATE_B", reference_content="PRIVATE_C")
        clean = public_input(ext_id, fake)
        assert set(clean) == set(fields)
        assert all(v["expected"] == "legitimate nested note" for v in clean.values())
        base = type("Dummy" + ext_id.replace("-", ""), (ExtAdapter,), {
            "EXT_ID": ext_id, "build_input": lambda self, tid, obs=fake: obs,
            "run_task": lambda self, tid, sut, budget, obs=fake: (sut(obs) and self.record(
                ext_id=self.EXT_ID, source_task_id=tid, prompt_or_scene={}))})
        adapter = base()
        assert set(adapter.build_input("a")) == set(fields)
        received = []
        adapter.run_task("a", lambda obs: received.append(obs) or {"text": "no gold used"},
                         {"evaluation_mode": "component_self_test"})
        assert len(received) == 1 and set(received[0]) == set(fields)


@pytest.mark.parametrize("ext_id", ["EXT-1", "EXT-2", "EXT-3", "EXT-4", "EXT-9", "EXT-10", "EXT-11", "EXT-12", "EXT-13", "EXT-14", "EXT-15"])
def test_installed_legacy_data_build_and_callback(ext_id):
    import ext_common as xc
    from adapter_base import PUBLIC_INPUT_FIELDS
    # Asset-free development checkouts still exercise the synthetic boundary
    # test; this extra integration check runs against actual installed assets.
    if not (Path(xc.HERE) / ext_id / "data").exists():
        pytest.skip("legacy public asset folder absent, not an SUT failure")
    adapter = xc.load_adapter(ext_id)
    tasks = adapter.list_tasks()
    assert tasks
    for tid in (tasks[0], tasks[-1]):
        public = adapter.build_input(tid)
        assert public and set(public) <= set(PUBLIC_INPUT_FIELDS[ext_id])
    received = []
    callback = lambda obs: received.append(obs) or {"text": "synthetic boundary control", "partial_status": "PARTIAL"}
    if ext_id == "EXT-12":
        with pytest.raises(xc.UpstreamUnavailable):
            adapter.run_task(tasks[0], callback, {"evaluation_mode": "component_self_test"})
        assert received == []
    else:
        record = adapter.run_task(tasks[0], callback, {"evaluation_mode": "component_self_test"})
        assert len(received) == 1
        assert set(received[0]) <= set(PUBLIC_INPUT_FIELDS[ext_id])
        assert record["derived"]["partial_status"] == "PARTIAL"
