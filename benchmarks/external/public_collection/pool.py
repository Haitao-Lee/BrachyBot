"""Typed public/private protocol adapters. No model invocation or auto-judge.

Use list/build/export for construction and audited upstream scorers for later
offline predictions. Interactive cases remain cases, not flattened QA rows.
"""
from __future__ import annotations

import argparse
import ast
import copy
import csv
from dataclasses import dataclass
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys
import types
import zipfile

from .collect import ROOT, confined, read_json, sha256, verify, write_json


class ProtocolBlocked(RuntimeError):
    """Missing original protocol/dependency, not an unsuccessful SUT result."""


@dataclass(frozen=True)
class Task:
    source_id: str
    cluster: str
    public: dict
    private: dict
    subset: str


def jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def csv_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def opaque(value):
    import hashlib
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def options(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = ast.literal_eval(value)  # literal only, never eval
    if not isinstance(value, dict) or not value:
        raise ValueError("nonempty option mapping required")
    return copy.deepcopy(value)


class PublicPool:
    def __init__(self, ext_id, root=ROOT):
        self.root = Path(root).resolve()
        self.ext_id = ext_id
        self.entry = next(e for e in read_json(self.root / "catalog.json")["benchmarks"] if e["id"] == ext_id)
        self.folder = self.root / "assets" / ext_id
        self._tasks = None
        self.exclusions = {}
        self.blocked_source_ids = []
        self.corpora = {}

    def _add(self, out, source_id, cluster, public, private, subset):
        tid = opaque(self.ext_id + ":" + str(source_id))
        if tid in out:
            raise ValueError("duplicate task ID")
        out[tid] = Task(str(source_id), str(cluster), public, private, subset)

    def _load(self):
        if self._tasks is not None:
            return self._tasks
        out = {}
        f = self.folder
        add = lambda sid, cluster, public, private, subset: self._add(out, sid, cluster, public, private, subset)
        if self.ext_id == "EXT-16":
            for subset in ("mcq", "llm_judge"):
                for r in jsonl(f / "data/test" / f"when2call_test_{subset}.jsonl"):
                    public = {"question": r["question"], "tools": copy.deepcopy(r["tools"])}
                    if subset == "mcq":
                        # All choices are public, never the correct choice/category.
                        public["candidates"] = list(r["answers"].values())
                    add(subset + ":" + r["uuid"], r.get("source_id") or r["uuid"], public, r, subset)
        elif self.ext_id == "EXT-17":
            for path in sorted((f / "data").glob("BFCL_v3_*.json")):
                subset = path.stem.removeprefix("BFCL_v3_")
                answer_path = path.parent / "possible_answer" / path.name
                gold = {r["id"]: r["ground_truth"] for r in jsonl(answer_path)} if answer_path.exists() else {}
                for r in jsonl(path):
                    if "irrelevance" not in subset and r["id"] not in gold:
                        # Known upstream orphan is not paired by zip/order or
                        # assigned an invented reference answer.
                        self.blocked_source_ids.append({"subset": subset, "id": r["id"], "reason": "missing_task_owned_gold"})
                        continue
                    if "irrelevance" in subset:
                        answer = []  # Official irrelevance protocol has no calls.
                    else:
                        answer = gold[r["id"]]
                    add(r["id"], r["id"], {"messages": copy.deepcopy(r["question"]), "tools": copy.deepcopy(r["function"])},
                        {"function": r["function"], "ground_truth": answer}, subset)
        elif self.ext_id == "EXT-18":
            for subset in ("Text", "MM"):
                for r in jsonl(f / "data" / subset / "test.jsonl"):
                    public = {"question": r["question"], "options": options(r["options"])}
                    if subset == "MM":
                        public["image_refs"] = [opaque(name) for name in r["images"]]
                    add(r["id"], r["id"], public, r, subset)
        elif self.ext_id == "EXT-19":
            for r in read_json(f / "data/CMB-Clin-qa.json"):
                first = "以下是一位病人的病例：\n" + r["description"] + "\n" + r["QA_pairs"][0]["question"]
                add(r["id"], r["id"], {"messages": [{"role": "user", "content": first}]},
                    {"answers": [q["answer"] for q in r["QA_pairs"]],
                     "case_description": r["description"],
                     "user_turns": [q["question"] for q in r["QA_pairs"]]}, "clin_cases")
        elif self.ext_id == "EXT-20":
            blank = 0
            for r in csv_rows(f / "vendor/MEDEC-MS/MEDEC-MS-TestSet-with-GroundTruth-and-ErrorType.csv"):
                if not any(r.values()):
                    blank += 1
                    continue  # Upstream file has 328 completely empty trailing rows.
                if not r["Text ID"].startswith("ms-test-") or not r["Text"]:
                    raise ValueError("unidentified/non-MS text cannot be admitted")
                add(r["Text ID"], r["Text ID"], {"clinical_text": r["Text"], "sentences": r["Sentences"]}, r, "MS_test")
            self.exclusions["upstream_blank_rows"] = blank
        elif self.ext_id == "EXT-21":
            for path in sorted((f / "data").rglob("*.csv")):
                subset = path.stem
                excluded = 0
                for r in csv_rows(path):
                    if subset.startswith("reasoning"):
                        if r["split_type"] != "test":
                            excluded += 1
                            continue
                        public = {"question": r["question"], "options": options(r["options"])}
                        if subset == "reasoning_FCT":
                            # Student's possibly wrong claim is the actual task input,
                            # not the reference answer or student-index label.
                            public["student_answer"] = r["student_answer"]
                        cluster = "question:" + opaque(str(r["dataset"]) + ":" + " ".join(r["question"].split()))
                    else:
                        # IR tasks ask for a specific title/PMID/abstract mapping;
                        # returning the whole publication metadata would leak gold.
                        field = {"IR_pmid2title": "PMID", "IR_pubmedlink2title": "url",
                                 "IR_title2pubmedlink": "source_title", "IR_abstract2pubmedlink": "source_abstract"}[subset]
                        public = {"input": r[field]}
                        cluster = "reference:" + str(r.get("PMID") or r.get("DOI") or r["source_title"])
                    add(subset + ":" + r["id"], cluster, public, r, subset)
                self.exclusions[subset + "_non_test"] = excluded
        elif self.ext_id == "EXT-22":
            import pyarrow.parquet as pq
            for path in sorted((f / "data/data").glob("*.parquet")):
                subset = path.name.split("-")[0]
                for r in pq.read_table(path).to_pylist():
                    # No context concoction: the original sampling/judge gate has
                    # not been certified. Inspect tasks without leaking doc roles.
                    public = {"question": r["question"], "options": json.loads(r["options"] or "{}")}
                    add(r["question_id"], r["question_id"], public, r, subset)
        elif self.ext_id in ("EXT-23", "EXT-24", "EXT-25"):
            if self.ext_id == "EXT-23":
                dirs = [f / name for name in ("PMC-Treatment", "PMC-Clinical", "IIYi-Clinical", "MedQA-Diag")]
            else:
                dirs = [f / "data" / ("nfcorpus" if self.ext_id == "EXT-24" else "scifact")]
            for folder in dirs:
                subset = folder.name
                raw_corpus = jsonl(folder / "corpus.jsonl")
                unique = {}
                for record in raw_corpus:
                    pid = str(record.get("id", record.get("_id")))
                    if pid in unique and unique[pid] != record:
                        raise ValueError("conflicting corpus id: " + subset + ":" + pid)
                    unique[pid] = record
                corpus = list(unique.values())
                corpus_ids = set(unique)
                self.exclusions[subset + "_identical_corpus_duplicates"] = len(raw_corpus) - len(corpus)
                self.corpora[subset] = corpus
                qrels = {}
                if self.ext_id == "EXT-23":
                    rels = jsonl(folder / "qrels.jsonl")
                    queries = jsonl(folder / "query.jsonl")
                    for r in rels:
                        qrels.setdefault(str(r["q_id"]), {})[str(r["p_id"])] = int(r["score"])
                else:
                    with (folder / "qrels/test.tsv").open() as stream:
                        for r in csv.DictReader(stream, delimiter="\t"):
                            qrels.setdefault(r["query-id"], {})[r["corpus-id"]] = int(r["score"])
                    queries = jsonl(folder / "queries.jsonl")
                qids = set()
                for r in queries:
                    qid = str(r.get("id", r.get("_id")))
                    if qid not in qrels:
                        continue
                    if qid in qids:
                        raise ValueError("duplicate test query id")
                    qids.add(qid)
                    if set(qrels[qid]) - corpus_ids:
                        raise ValueError("qrels refers to absent corpus document")
                    corpus_key = opaque(self.ext_id + ":" + subset)
                    add(subset + ":" + qid, subset + ":" + qid,
                        {"query": r["text"], "corpus_id": corpus_key},
                        {"query_id": qid, "qrels": qrels[qid]}, subset)
                if qids != set(qrels):
                    raise ValueError("qrels missing query text")
                self.exclusions[subset + "_non_test_queries"] = len(queries) - len(qids)
        elif self.ext_id == "EXT-26":
            for patient_id, r in read_json(f / "vendor/data/benchmark_v5.json").items():
                for i, q in enumerate(r["questions"]):
                    # Documents get indistinguishable IDs; no answer_location or
                    # diagnosis metadata. Native shuffled/context-limited prompts
                    # are rendered only through the original create_prompt below.
                    public = {"documents": list(r["texts"].values()), "question": q["question"],
                              "options": {k.upper(): q["answer_" + k] for k in "abcde"}}
                    add(patient_id + ":" + str(i), patient_id, public, {"patient": r, "question": q}, "task1_base")
        elif self.ext_id == "EXT-27":
            tool_map = {}
            for kit in read_json(f / "vendor/data/tools.json"):
                for tool in kit["tools"]:
                    tool = copy.deepcopy(tool)
                    tool["name"] = kit["toolkit"] + tool["name"]
                    tool_map[tool["name"]] = tool
            for attack in ("dh", "ds"):
                for variant in ("base", "enhanced"):
                    for i, r in enumerate(read_json(f / f"vendor/data/test_cases_{attack}_{variant}.json")):
                        names = [r["User Tool"]] + r["Attacker Tools"]
                        public = {"tools": [copy.deepcopy(tool_map[n]) for n in names],
                            "messages": [
                                {"role": "user", "content": r["User Instruction"]},
                                {"role": "assistant", "tool_calls": [{"id": "injected-observation",
                                    "name": r["User Tool"], "arguments": copy.deepcopy(r["Tool Parameters"])}]},
                                {"role": "tool", "tool_call_id": "injected-observation",
                                    "name": r["User Tool"], "content": copy.deepcopy(r["Tool Response"])}]}
                        # Variant is a repeated view; attacker goals and simulated
                        # second-stage responses never become user instructions.
                        add(f"{attack}:{variant}:{i}", f"{attack}:{i}", public, r, attack + "_" + variant)
        else:
            raise ValueError("unknown collection protocol")
        if not out:
            raise ValueError("no eligible test tasks")
        self._tasks = out
        return out

    def list_tasks(self):
        return list(self._load())

    def task(self, task_id):
        return self._load()[task_id]

    def build_input(self, task_id):
        """Only the declared public schema; no gold-dependent generic stripping."""
        if self.ext_id == "EXT-22":
            raise ProtocolBlocked("MedRGB data available; original context composition/runner not certified. Raw data is not a runnable RAG protocol.")
        return copy.deepcopy(self.task(task_id).public)

    def image_bytes(self, task_id):
        if self.ext_id != "EXT-18":
            raise ValueError("not a multimodal task")
        r = self.task(task_id).private
        with zipfile.ZipFile(self.folder / "data/images.zip") as archive:
            data = []
            for name in r.get("images", []):
                member = "images/" + name
                confined(self.folder, member)
                info = archive.getinfo(member)
                if info.file_size > 32 * 1024 ** 2:
                    raise ValueError("unexpected image size")
                data.append(archive.read(member))
            return data

    def cmb_messages(self, task_id, previous_responses):
        t = self.task(task_id)
        if self.ext_id != "EXT-19" or len(previous_responses) >= len(t.private["user_turns"]):
            raise ValueError("invalid CMB case turn")
        messages = []
        for i in range(len(previous_responses) + 1):
            question = t.private["user_turns"][i]
            if i == 0:
                question = "以下是一位病人的病例：\n" + t.private["case_description"] + "\n" + question
            messages.append({"role": "user", "content": question})
            if i < len(previous_responses):
                if not isinstance(previous_responses[i], str):
                    raise TypeError("previous model response must be text")
                messages.append({"role": "assistant", "content": previous_responses[i]})
        return messages

    def _module(self, relative, qualified_name=None):
        """Explicitly import a reviewed local scorer only after its file hash passes."""
        path = confined(self.root, "assets/" + self.ext_id + "/" + relative)
        lock = read_json(self.root / "assets.lock.json")["files"]
        rel = path.relative_to(self.root).as_posix()
        if rel not in lock or sha256(path) != lock[rel]["sha256"]:
            raise ProtocolBlocked("upstream scorer missing/changed")
        self._verify_vendor_sources()
        spec = importlib.util.spec_from_file_location(qualified_name or "_public_scorer_" + opaque(rel), path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except (ImportError, FileNotFoundError) as e:
            raise ProtocolBlocked("original scorer dependency missing: " + str(e)) from e
        return module

    def _verify_vendor_sources(self):
        lock = read_json(self.root / "assets.lock.json")["files"]
        for path in (self.folder / "vendor").rglob("*.py"):
            rel = path.relative_to(self.root).as_posix()
            if rel not in lock or sha256(path) != lock[rel]["sha256"]:
                raise ProtocolBlocked("unlocked/modified scorer dependency")

    def _namespace(self, name, relative):
        """Private benchmark process only; refuse to shadow an installed package."""
        path = confined(self.folder, relative)
        existing = sys.modules.get(name)
        if existing and list(getattr(existing, "__path__", [])) != [str(path)]:
            raise ProtocolBlocked("upstream namespace already in use: " + name)
        if not existing:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package

    def score_bfcl(self, task_id, canonical_calls):
        """Delegate original AST equivalence; don't execute the proposed calls."""
        if self.ext_id != "EXT-17" or not isinstance(canonical_calls, list):
            raise TypeError("BFCL expects canonical parsed calls, not prose")
        t = self.task(task_id)
        if "irrelevance" in t.subset:
            # Separate native irrelevance metric, never an AST/treatment score.
            return {"upstream_irrelevance_accuracy": int(len(canonical_calls) == 0),
                    "protocol": "bfcl_irrelevance_no_tool_calls"}
        self._verify_vendor_sources()
        self._namespace("bfcl", "vendor/berkeley-function-call-leaderboard/bfcl")
        module = self._module("vendor/berkeley-function-call-leaderboard/bfcl/eval_checker/ast_eval/ast_checker.py")
        return module.ast_checker(t.private["function"], canonical_calls,
            t.private["ground_truth"], "Python", t.subset, "common_harness_prompting")

    def score_retrieval(self, predictions, subset, k_values=(1, 3, 5, 10, 100)):
        """Only ranked IDs/scores; complete test query coverage mandatory."""
        if self.ext_id not in ("EXT-23", "EXT-24", "EXT-25"):
            raise ValueError("not a retrieval benchmark")
        tasks = {tid: t for tid, t in self._load().items() if t.subset == subset}
        if not tasks or set(predictions) != set(tasks):
            raise ValueError("predictions must cover exactly the selected test queries")
        if not k_values or any(not isinstance(k, int) or k < 1 for k in k_values):
            raise ValueError("positive cutoffs required")
        corpus_ids = {str(r.get("id", r.get("_id"))) for r in self.corpora[subset]}
        qrels, results = {}, {}
        for tid, t in tasks.items():
            rank = predictions[tid]
            if not isinstance(rank, dict) or set(rank) - corpus_ids:
                raise ValueError("ranked result references missing corpus document")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rank.values()):
                raise ValueError("finite ranking scores required")
            qid = t.private["query_id"]
            qrels[qid] = t.private["qrels"]
            results[qid] = copy.deepcopy(rank)
        # R2MED uses the BEIR metric implementation. Share the identical pinned
        # scorer, not R2MED's model-loading module (which would start retrievers).
        scoring_pool = self if self.ext_id == "EXT-24" else PublicPool("EXT-24", self.root)
        scoring_pool._verify_vendor_sources()
        scoring_pool._namespace("beir", "vendor/beir")
        module = scoring_pool._module("vendor/beir/retrieval/evaluation.py", "beir.retrieval.evaluation")
        return module.EvaluateRetrieval.evaluate(qrels, results, list(k_values), ignore_identical_ids=True)

    def when2call_prompt(self, task_id):
        if self.ext_id != "EXT-16":
            raise ValueError("wrong benchmark")
        t = self.task(task_id)
        if t.subset != "mcq":
            raise ProtocolBlocked("free-generation judge protocol requires the upstream judge runner")
        module = self._module("vendor/evaluation/mcq/lm_eval_harness/when2call/utils.py")
        # Original Dataset.map prompt renderer, but return only public fields.
        from datasets import Dataset
        rendered = module.process_docs_default(Dataset.from_list([t.private]))[0]
        return {"prompt": rendered["prompt"], "candidates": rendered["choices"]}

    def longhealth_prompt(self, task_id, tokenizer, max_tokens, seed):
        if self.ext_id != "EXT-26" or tokenizer is None:
            raise ValueError("LongHealth native rendering requires a fixed tokenizer/context setting")
        module = self._module("vendor/utils.py")
        t = self.task(task_id)
        q, patient = t.private["question"], t.private["patient"]
        answer_docs = {i: patient["texts"][i] for i in q["answer_location"]}
        others = [text for i, text in patient["texts"].items() if i not in q["answer_location"]]
        saved = random.getstate()
        random.seed(seed)
        try:
            # Exact native task1 budget: reserve system-prompt tokens first.
            prompt, _ = module.create_prompt(answer_docs, others, q, tokenizer=tokenizer,
                max_len=max_tokens - len(tokenizer.encode(module.SYSTEM_PROMPT)))
        finally:
            random.setstate(saved)
        return {"system": module.SYSTEM_PROMPT, "prompt": prompt}

    def score_medxpert(self, task_id, response_text):
        if self.ext_id != "EXT-18" or not isinstance(response_text, str):
            raise ValueError("MedXpert response must be text")
        module = self._module("vendor/eval/utils.py")
        task = self.task(task_id)
        pred = module.answer_cleansing("zero_shot", "The answer is", response_text,
                                      "medxpertqa", "Multiple Choice", task.private)
        return {"upstream_accuracy": module.compute_accuracy(pred, [task.private["label"]]),
                "evaluation_mode": "upstream_prediction_scoring"}

    def summary(self):
        from collections import Counter
        tasks = self._load()
        return {"id": self.ext_id, "name": self.entry["name"], "eligible_task_units": len(tasks),
                "clusters": len({t.cluster for t in tasks.values()}),
                "subsets": dict(Counter(t.subset for t in tasks.values())),
                "user_turns": sum(len(t.private.get("user_turns", [])) for t in tasks.values()),
                "exclusions": self.exclusions,
                "blocked_source_ids": self.blocked_source_ids,
                "corpus_documents": {k: len(v) for k, v in self.corpora.items()},
                "data_collected": True, "protocol_fidelity_certified": False, "sut_runs": 0,
                "score_gate": "upstream_runner_and_comparator_configuration_required"}


def export_public(pool, output):
    """Create a corpus/inputs-only bundle; never copy raw assets, qrels or gold.

    Mount just this bundle in the SUT sandbox, never external/assets or the
    benchmark checkout. Its manifest explicitly is NOT a native run result.
    """
    output = Path(output).resolve()
    # New destinations only: don't overwrite or recursively remove user artifacts.
    if output.exists():
        raise FileExistsError("export destination must not already exist")
    if pool.ext_id == "EXT-22":
        raise ProtocolBlocked("MedRGB sampling/scoring fidelity gate not satisfied")
    output.mkdir(parents=True)
    files = []
    with (output / "inputs.jsonl").open("w", encoding="utf-8") as out:
        for tid in pool.list_tasks():
            public = pool.build_input(tid)
            if pool.ext_id == "EXT-18" and "image_refs" in public:
                image_files = []
                for ref, data in zip(public["image_refs"], pool.image_bytes(tid), strict=True):
                    if data.startswith(b"\xff\xd8\xff"):
                        extension, mime = ".jpg", "image/jpeg"
                    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
                        extension, mime = ".png", "image/png"
                    else:
                        raise ValueError("unsupported test image encoding")
                    p = output / "images" / (ref + extension)
                    p.parent.mkdir(exist_ok=True)
                    p.write_bytes(data)
                    image_files.append({"ref": ref, "path": p.relative_to(output).as_posix(), "mime_type": mime})
                public["image_files"] = image_files
            out.write(json.dumps({"id": tid, "input": public}, ensure_ascii=False) + "\n")
    for subset, corpus in pool.corpora.items():
        key = opaque(pool.ext_id + ":" + subset)
        with (output / (key + ".corpus.jsonl")).open("w", encoding="utf-8") as stream:
            for r in corpus:
                record = {"id": str(r.get("id", r.get("_id"))), "text": r["text"]}
                if r.get("title"):
                    record["title"] = r["title"]
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    for p in sorted(output.rglob("*")):
        if p.is_file():
            files.append({"path": p.relative_to(output).as_posix(), "sha256": sha256(p)})
    write_json(output / "PUBLIC_MANIFEST.json", {"benchmark": pool.ext_id, "files": files,
               "no_gold": True, "native_protocol_certified": False, "mode": "public_input_bundle_not_run_result"})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["inventory", "export"])
    p.add_argument("--id")
    p.add_argument("--out")
    a = p.parse_args()
    if a.action == "export":
        if not a.id or not a.out:
            p.error("export requires --id and --out")
        if verify()["problems"]:
            raise ProtocolBlocked("collection integrity failed")
        export_public(PublicPool(a.id), a.out)
        return 0
    rows = [PublicPool(e["id"]).summary() for e in read_json(ROOT / "catalog.json")["benchmarks"] if not a.id or e["id"] == a.id]
    print(json.dumps({"benchmarks": rows, "evaluation_mode": "collection_validation", "sut_runs": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
