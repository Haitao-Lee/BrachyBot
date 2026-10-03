"""Deterministic compilation of hand-authored candidates; no SUT execution."""
import argparse
import hashlib
import json
from pathlib import Path
if __package__:
    from .catalog import PACK
    from .quality_gate import validate
else:
    from catalog import PACK
    from quality_gate import validate

def outputs():
    pack = dict(PACK)
    pack["catalog_sha256"] = hashlib.sha256(Path(__file__).with_name("catalog.py").read_bytes()).hexdigest()
    quality = validate(pack)
    if not quality["structural_ok"]:
        raise ValueError("\n".join(quality["errors"]))
    encode = lambda value: json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return {"candidate_pack.json": encode(pack), "authoring_quality.json": encode(quality)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check candidate compilation only, not formal benchmark readiness")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    for name, content in outputs().items():
        target = base / name
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                raise SystemExit(f"candidate compilation drift: {name}")
        else:
            target.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({"authoring_contract_ok": True, "families": PACK["family_count"], "scenarios": PACK["scenario_count"],
                      "formal_ready": False, "live_runs": 0, "semantic_validity": "NOT_ESTABLISHED"}))

if __name__ == "__main__":
    main()
