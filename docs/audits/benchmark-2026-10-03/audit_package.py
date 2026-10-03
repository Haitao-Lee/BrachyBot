"""Publish new audit documentation only; never overwrite an existing target."""
import collections
import csv
import datetime
import gzip
import hashlib
import io
import json
import pathlib
import re
import tarfile

REPO = pathlib.Path('/home/lht/snap/brachyplan/BrachyBot')
SOURCE = pathlib.Path('/tmp/brachybench-audit-evidence-20261003')
ARCHIVE = pathlib.Path('/tmp/brachybench-audit-20261003-source.tar.gz')
REPORT_SOURCE = pathlib.Path('/tmp/brachybench-independent-report-20261003.md')
REPORT_TARGET = REPO / 'docs/BENCHMARK_INDEPENDENT_AUDIT_2026-10-03.md'
OUT = REPO / 'docs/audits/benchmark-2026-10-03'
BASELINE = {
    'benchmarks/BENCHMARK_REPORT.md': '781e6f9b94bf9f20c79a79b70f305a3f985c5b576331f0f977722b13bd025048',
    'docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md': '3ef1d252b8ac11a0230ba0858266574f78940c863f659487fd81e213e9746feb',
    'benchmarks/brachybench/tools/run_task.py': '5171878d5e6b6db10bd2e898a0b2db9b07e65ed2ed9a3e23200aec5b9c6320d8',
    'benchmarks/brachybench/oracles/geom.py': 'cb85868ed23b391bfb5ac88f7465056ea60715f7d022210b516ed115a7efd3a9',
}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def compressed(data):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0) as stream:
        stream.write(data)
    return buffer.getvalue()

assert not REPORT_TARGET.exists(), str(REPORT_TARGET)
assert not OUT.exists(), str(OUT)
for name, expected in BASELINE.items():
    assert digest((REPO / name).read_bytes()) == expected, 'Source changed: ' + name

report = REPORT_SOURCE.read_bytes()
assert len(re.findall(r'### AUD-\d+[：:]', report.decode('utf-8'))) == 32
rows = [json.loads(line) for line in (SOURCE / 'per_item_recommendations.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(rows) == 11969
assert len({row['id'] for row in rows}) == 11969
with (SOURCE / 'per_item_index.csv').open(encoding='utf-8-sig', newline='') as stream:
    index = list(csv.DictReader(stream))
assert len(index) == 11969
state_diff = [row for row in index if row['check'] == 'state_diff']
assert len(state_diff) == 325
assert sum(row['both_noop_verdict'] == 'Meets' for row in state_diff) == 324
final = json.loads((SOURCE / 'audit_final.json').read_text(encoding='utf-8'))
assert all(check['exit_code'] == 0 for check in final['repository_checks'])

payloads = {}
for name in ('inventory_deep.json', 'audit_extra.json', 'audit_final.json', 'counterexamples_verified.json'):
    payloads[name] = (SOURCE / name).read_bytes()
for stem in ('validate', 'quality_audit', 'coverage', 'hash_manifest'):
    for suffix in ('stdout', 'stderr'):
        name = f'{stem}_{suffix}.txt'
        payloads[name] = (SOURCE / name).read_bytes()
for name in ('per_item_recommendations.jsonl', 'per_item_index.csv'):
    payloads[name + '.gz'] = compressed((SOURCE / name).read_bytes())
for short in ('deep', 'extra', 'finalize'):
    payloads['audit_' + short + '.py'] = pathlib.Path('/tmp/brachybench-audit-' + short + '-20261003.py').read_bytes()
payloads['audit_package.py'] = pathlib.Path(__file__).read_bytes()

source_manifest = []
with tarfile.open(ARCHIVE, 'r:gz') as archive:
    for member in archive:
        if not member.isfile():
            continue
        stream = archive.extractfile(member)
        content = stream.read()
        source_manifest.append({'path': member.name, 'bytes': len(content), 'sha256': digest(content)})
source_manifest.sort(key=lambda row: row['path'])
payloads['source_snapshot_hashes.json.gz'] = compressed(json.dumps(source_manifest, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

readme = '''# Audit evidence: 2026-10-03

Scope: read-only audit of the remote working tree, HEAD 7aa6d23086072b593beba069f8c2116d01c3c0f3. The working tree was dirty; HEAD alone does not identify the evaluated source. source_snapshot_hashes.json.gz identifies the inspected authored snapshot. Large external vendor/data/model assets were outside this snapshot and were not run.

The report is ../../BENCHMARK_INDEPENDENT_AUDIT_2026-10-03.md. All 11,969 task records were read programmatically. Manual analysis covers evaluator mechanisms and representative families, NOT 11,969 independent clinical adjudications. Automated flags are triage, not final item-error labels.

Files:
- per_item_recommendations.jsonl.gz: one record per task, including request, file, checker, flags, actual counterexample verdicts, and recommendations.
- per_item_index.csv.gz: compact UTF-8 BOM CSV index for filtering; 325 state_diff records, 324 with both_noop_verdict=Meets.
- counterexamples_verified.json: successfully executed probes; exploratory failed-call probes removed.
- inventory_deep.json and audit_extra.json: inventory and grouping/split details; candidate contradictions require human adjudication.
- audit_final.json and *_stdout/stderr.txt: final supplementary probes and four native validation command results.
- audit_deep.py / audit_extra.py / audit_finalize.py: read-only derived-audit scripts. They write only into a separately supplied audit output directory. Do not point that output at tasks, gold, source, or historical results.
- source_snapshot_hashes.json.gz and MANIFEST.json: provenance, scope and SHA-256 hashes.

Reproduction in a separate temporary directory with numpy/scipy available:
1. mkdir -p /tmp/brachybench-independent-audit-reproduction
2. python audit_deep.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction
3. python audit_extra.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction
4. python audit_finalize.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction

Inspect each script's positional argument contract before reuse; run against the recorded snapshot or explicitly disclose subsequent drift. No live agent/provider/GPU/browser evaluation was performed. No source, existing benchmark items, existing scores, or services were changed. audit_package.py is the one-time no-overwrite publisher for this report, not a benchmark runner.
'''
payloads['README.md'] = readme.encode('utf-8')
manifest = {
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'baseline_head': '7aa6d23086072b593beba069f8c2116d01c3c0f3',
    'dirty_working_tree': True,
    'scope': 'Pure benchmark evaluators and exhaustive automated item audit; no clinical/live-system performance claim',
    'task_count': len(rows),
    'track_counts': dict(collections.Counter(row['track'] for row in rows)),
    'source_archive_path_at_audit': str(ARCHIVE),
    'source_archive_sha256': digest(ARCHIVE.read_bytes()),
    'source_snapshot_files': len(source_manifest),
    'rechecked_baseline_source_files': BASELINE,
    'report': {'path': str(REPORT_TARGET), 'sha256': digest(report), 'bytes': len(report), 'findings': 32},
    'artifacts': {name: {'sha256': digest(data), 'bytes': len(data)} for name, data in sorted(payloads.items())},
    'native_checks': final['repository_checks'],
}
payloads['MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.mkdir(exist_ok=False)
for name, data in payloads.items():
    with (OUT / name).open('xb') as stream:
        stream.write(data)
with REPORT_TARGET.open('xb') as stream:
    stream.write(report)
for name, data in payloads.items():
    assert digest((OUT / name).read_bytes()) == digest(data)
assert digest(REPORT_TARGET.read_bytes()) == digest(report)
for name, expected in BASELINE.items():
    assert digest((REPO / name).read_bytes()) == expected, 'Source changed during publication: ' + name
print(json.dumps({'report': str(REPORT_TARGET), 'evidence': str(OUT), 'task_records': len(rows),
                  'findings': 32, 'artifact_count': len(payloads), 'total_artifact_bytes': sum(map(len, payloads.values())),
                  'report_sha256': digest(report), 'source_snapshot_files': len(source_manifest)}, ensure_ascii=False))
