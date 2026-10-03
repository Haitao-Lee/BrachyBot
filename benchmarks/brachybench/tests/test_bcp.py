"""BCP corpus-construction tests (DESIGN §30.4-§30.5).

Prove the harvest and cluster tools are deterministic and operate on the real
archived intents (no invented text).
"""

from __future__ import annotations

import json
import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from tools.bcp import cluster as cl  # noqa: E402
from tools.bcp import harvest as hv  # noqa: E402


def _run_harvest(tmp_path):
    out = os.path.join(str(tmp_path), "intents")
    rc = hv.main(["--legacy", os.path.join(BB, "migration", "legacy_intents.jsonl"),
                  "--out", out])
    assert rc == 0
    recs = [json.loads(l) for l in open(os.path.join(out, "intents.jsonl"), encoding="utf-8")]
    return recs


def test_harvest_reads_all_legacy_intents_and_hashes(tmp_path):
    recs = _run_harvest(tmp_path)
    assert len(recs) == 1765
    assert all(len(r["raw_sha256"]) == 64 for r in recs)
    assert all(r["intent_id"].startswith("INT-") for r in recs)
    assert len({r["intent_id"] for r in recs}) == len(recs), "intent ids must be unique"


def test_harvest_redacts_identifiers(tmp_path):
    recs = _run_harvest(tmp_path)
    assert any(r["redaction_ledger"] for r in recs), "expected some scrub targets"
    # no raw email survives the pass
    assert not any("@" in (r["redacted_text"] or "") for r in recs)


def test_cluster_is_deterministic(tmp_path):
    recs = _run_harvest(tmp_path)
    t1 = cl.cluster_records(recs, threshold=0.35, min_size=2)
    t2 = cl.cluster_records(list(reversed(recs)), threshold=0.35, min_size=2)
    assert [t["template_id"] for t in t1] == [t["template_id"] for t in t2]
    assert all(t["gold_status"] == "draft" and t["expectation"] is None for t in t1)
    assert all(t["n_source_intents"] >= 2 for t in t1)
    assert len(t1) > 50


def test_committed_corpus_artifacts_exist():
    assert os.path.isfile(os.path.join(BB, "corpus", "intents", "intents.jsonl"))
    summ = os.path.join(BB, "corpus", "templates", "_summary.json")
    assert os.path.isfile(summ)
    with open(summ, encoding="utf-8") as fh:
        s = json.load(fh)
    assert s["n_intents"] == 1765 and s["n_templates"] > 50
