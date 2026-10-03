#!/usr/bin/env python3
"""BCP · P2 cluster: normalised intents -> candidate scenario templates.

DESIGN §30.5.  Real user phrasing for the *same* intent varies, so the unit we
want is a **template** (an intent family), not a single sentence.  This tool
clusters harvested intents deterministically:

1. group by legacy ``category`` (coarse intent domain);
2. within a category, single-link cluster on a dependency-free similarity
   (English word tokens + CJK character bigrams, Jaccard);
3. emit one candidate ``TPL-*`` per sub-cluster, with its source intents.

The output is **candidates for expert authoring** -- it carries no expectation
model and no gold status.  Clustering only proposes groupings; a human decides.

    python tools/bcp/cluster.py --intents corpus/intents/intents.jsonl \
        --out corpus/templates --threshold 0.5 --min-size 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, "..", ".."))

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "are", "be", "can", "could", "would", "you", "your", "i", "we", "me", "my",
    "please", "help", "this", "that", "it", "do", "does", "have", "has", "need",
    "want", "how", "what", "which", "from", "at", "as", "about", "if",
}


def features(text: str) -> frozenset:
    t = (text or "").lower()
    toks = {w for w in _WORD.findall(t) if len(w) >= 2 and w not in _STOP}
    chars = _CJK.findall(text or "")
    toks |= {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    return frozenset(toks)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def cluster_records(records: Sequence[Dict[str, Any]], *, threshold: float,
                    min_size: int) -> List[Dict[str, Any]]:
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_cat[str(r.get("category"))].append(r)

    templates: List[Dict[str, Any]] = []
    for cat in sorted(by_cat):
        items = sorted(by_cat[cat], key=lambda r: r["intent_id"])
        feats = [features(r["redacted_text"]) for r in items]
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if jaccard(feats[i], feats[j]) >= threshold:
                    union(i, j)

        comps: Dict[int, List[int]] = defaultdict(list)
        for k in range(len(items)):
            comps[find(k)].append(k)

        for members in comps.values():
            if len(members) < min_size:
                continue
            # medoid: max total similarity, tie-break by intent_id (determinism)
            best, best_score = None, -1.0
            for k in members:
                score = sum(jaccard(feats[k], feats[m]) for m in members if m != k)
                if score > best_score or (score == best_score and
                                          items[k]["intent_id"] < items[best]["intent_id"]):
                    best, best_score = k, score
            refs = sorted(items[m]["intent_id"] for m in members)
            templates.append({
                "template_id": "TPL-" + hashlib.sha256(
                    ("|".join(refs)).encode("utf-8")).hexdigest()[:10],
                "category": cat,
                "facet": cat,
                "representative_text": items[best]["redacted_text"],
                "n_source_intents": len(refs),
                "source_refs": refs,
                "gold_status": "draft",
                "expectation": None,
                "_comment": "candidate for expert authoring (DESIGN §30.3); no oracle yet",
            })
    templates.sort(key=lambda t: (-t["n_source_intents"], t["template_id"]))
    return templates


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--intents", default=os.path.join(BB, "corpus", "intents", "intents.jsonl"))
    ap.add_argument("--out", default=os.path.join(BB, "corpus", "templates"))
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--min-size", type=int, default=2)
    args = ap.parse_args(argv)

    records = []
    with open(args.intents, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    templates = cluster_records(records, threshold=args.threshold, min_size=args.min_size)
    os.makedirs(args.out, exist_ok=True)
    index = []
    for t in templates:
        path = os.path.join(args.out, t["template_id"] + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(t, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        index.append({"template_id": t["template_id"], "category": t["category"],
                      "n": t["n_source_intents"]})

    digest = hashlib.sha256(json.dumps(index, sort_keys=True).encode("utf-8")).hexdigest()
    summary = {
        "n_intents": len(records),
        "n_templates": len(templates),
        "n_intents_in_templates": sum(t["n_source_intents"] for t in templates),
        "threshold": args.threshold,
        "min_size": args.min_size,
        "index_sha256": digest,
        "by_category": {c: sum(1 for t in templates if t["category"] == c)
                        for c in sorted({t["category"] for t in templates})},
    }
    with open(os.path.join(args.out, "_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
