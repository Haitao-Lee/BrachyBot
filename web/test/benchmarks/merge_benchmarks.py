#!/usr/bin/env python3
"""Merge 4 benchmark parts into one file, validate schema, deduplicate."""
import json, sys
from pathlib import Path

DIR = Path(__file__).parent

REQUIRED_FIELDS = ["id", "input", "expected_behavior", "expected_keywords",
                   "expected_keywords_operator", "validation_method",
                   "severity", "difficulty", "category"]

parts = []
for i in range(1, 5):
    f = DIR / f"benchmarks_part{i}.json"
    if f.exists():
        with open(f) as fh:
            data = json.load(fh)
            if isinstance(data, list):
                parts.extend(data)
                print(f"✅ Part {i}: {len(data)} questions loaded")
            else:
                print(f"❌ Part {i}: INVALID (not a list), skipping")
    else:
        print(f"⚠️  Part {i}: NOT FOUND")

# Validate schema
valid = []
schema_errors = []
for q in parts:
    missing = [f for f in REQUIRED_FIELDS if f not in q]
    if missing:
        schema_errors.append(f"{q.get('id','?')}: missing fields {missing}")
    else:
        valid.append(q)

# Deduplicate by input text (first 200 chars)
seen = set()
unique = []
dupes = 0
for q in valid:
    key = q.get("input", "").strip()[:200].lower()
    if key not in seen:
        seen.add(key)
        unique.append(q)
    else:
        dupes += 1

# Re-number IDs
for i, q in enumerate(unique):
    q["id"] = f"Q{i+1:04d}"

# Validate categories
cats = {}
for q in unique:
    c = q.get("category", "unknown")
    cats[c] = cats.get(c, 0) + 1

# Validate severity
sev_map = {}
for q in unique:
    s = q.get("severity", "unknown")
    sev_map[s] = sev_map.get(s, 0) + 1

# Validate difficulty
diff_map = {}
for q in unique:
    d = q.get("difficulty", "unknown")
    diff_map[d] = diff_map.get(d, 0) + 1

# Write merged file
out = DIR / "benchmark_2000.json"
with open(out, "w") as f:
    json.dump(unique, f, indent=2, ensure_ascii=False)

print(f"\n{'='*50}")
print(f"MERGE RESULTS")
print(f"{'='*50}")
print(f"Total loaded: {len(parts)}")
print(f"Schema errors: {len(schema_errors)}")
print(f"Duplicates removed: {dupes}")
print(f"Final unique: {len(unique)}")
print(f"\nCategories ({len(cats)}):")
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"  {c}: {n}")
print(f"\nSeverity distribution:")
for s, n in sorted(sev_map.items()):
    print(f"  {s}: {n}")
print(f"\nDifficulty distribution:")
for d, n in sorted(diff_map.items()):
    print(f"  {d}: {n}")
if schema_errors:
    print(f"\nSchema errors ({len(schema_errors)}):")
    for e in schema_errors[:10]:
        print(f"  {e}")
print(f"\nWritten to: {out}")
