"""Guard shared local helpers/constants used by the frozen latency baseline.

The manifest is generated from the recorded git revision, never from the
optimized checkout. Imported third-party implementations still require an
identical environment in paired runs; this is not a dependency lockfile.
"""
import ast
import hashlib


MODULE_PATHS = {
    'utilizations': 'plans/utilizations.py',
    'geometry': 'plans/geometry.py',
    'inference': 'plans/dose_pre/inference.py',
    'planning_pipeline': 'tool_factory/seed_plan/planning_pipeline.py',
}

# Cross-module calls and function-local imports are not plain global Name
# references. List these explicitly and follow their local dependencies too.
EXTRA_ROOTS = {
    'utilizations': ('infer_truncated_boundary_faces_from_image',),
    'geometry': ('voxel_to_world',),
}


def symbols(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.asname or n.name.split('.')[0] for n in node.names]
        else:
            continue
        for name in names:
            result[name] = node
    return result


def dependency_hashes(source, roots, extra_roots=()):
    table = symbols(source)
    pending = list(roots) + list(extra_roots)
    visited = set()
    result = {}
    while pending:
        name = pending.pop()
        if name in visited or name not in table:
            continue
        visited.add(name)
        node = table[name]
        if name not in roots:
            result[name] = hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
        pending.extend(n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
    return result


def verify_dependencies(repo, frozen):
    expected = frozen['dependency_hashes']
    for module, roots in frozen['functions'].items():
        # Read dependencies of the *frozen* functions, not the optimized
        # function bodies, which are deliberately allowed to change.
        source = (repo / MODULE_PATHS[module]).read_text()
        table = symbols(source)
        for name, digest in expected[module].items():
            assert name in table, f'Missing baseline dependency: {module}.{name}'
            actual = hashlib.sha256(ast.get_source_segment(source, table[name]).encode()).hexdigest()
            assert actual == digest, f'Baseline dependency drift: {module}.{name}; independently re-audit equivalence'
