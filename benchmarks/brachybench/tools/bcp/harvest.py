#!/usr/bin/env python3
"""BCP · P1 harvest: legacy intents -> normalised, hashed, redacted records.

DESIGN §30.4.  Reads the archived legacy clinical intents (real user-style
prompts), applies a conservative de-identification pass, and emits one
``intent_record`` per input with a content hash and a redaction ledger.  The
result is the *source material* for template clustering (P2).

Nothing here invents text: it only normalises and redacts what already exists.

    python tools/bcp/harvest.py --legacy migration/legacy_intents.jsonl \
        --out corpus/intents
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BB)

# --- conservative redaction (synthetic corpora still get scrubbed) ----------
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)")
_LONGID = re.compile(r"(?<!\d)\d{6,}(?!\d)")
_POSIXPATH = re.compile(r"(?<![\w])/(?:[\w.-]+/)+[\w.-]+")
_DR_NAME = re.compile(r"\bDr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
_AT_ORG = re.compile(r"\b(?:at|from)\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+(?:Hospital|Clinic|Center|Centre|Institute|University)\b")


def redact(text: str) -> tuple:
    ledger = {}
    out = text
    for name, rx, repl in (
        ("email", _EMAIL, "<EMAIL>"),
        ("phone", _PHONE, "<PHONE>"),
        ("long_id", _LONGID, "<ID>"),
        ("path", _POSIXPATH, "<PATH>"),
        ("person", _DR_NAME, "Dr. <PERSON>"),
        ("org", _AT_ORG, "at <ORG>"),
    ):
        out, n = rx.subn(repl, out)
        if n:
            ledger[name] = ledger.get(name, 0) + n
    return out, ledger


def _lang(text: str) -> str:
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if cjk and latin:
        return "mixed"
    return "zh" if cjk else "en"


def record(obj: Dict[str, Any]) -> Dict[str, Any]:
    raw = str(obj.get("input") or "")
    red, ledger = redact(raw)
    return {
        "intent_id": "INT-" + hashlib.sha256(
            f"{obj.get('source')}|{obj.get('id')}|{raw}".encode("utf-8")
        ).hexdigest()[:12],
        "legacy_id": obj.get("id"),
        "source": obj.get("source"),
        "category": obj.get("category"),
        "kind": obj.get("kind"),
        "lang": _lang(raw),
        "redacted_text": red,
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "triggers": obj.get("expected_keywords") or [],
        "expected_tool": obj.get("expected_tool"),
        "difficulty": obj.get("difficulty"),
        "turns": obj.get("turns"),
        "redaction_ledger": ledger,
        "_comment": "scorers from legacy are intentionally NOT carried over (DESIGN §20.2)",
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--legacy", default=os.path.join(BB, "migration", "legacy_intents.jsonl"))
    ap.add_argument("--out", default=os.path.join(BB, "corpus", "intents"))
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    n = 0
    redactions = 0
    out_path = os.path.join(args.out, "intents.jsonl")
    with open(args.legacy, encoding="utf-8") as fh, open(out_path, "w", encoding="utf-8") as out:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = record(json.loads(line))
            n += 1
            if rec["redaction_ledger"]:
                redactions += 1
            out.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"harvested {n} intents -> {out_path} ({redactions} contained scrub targets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
