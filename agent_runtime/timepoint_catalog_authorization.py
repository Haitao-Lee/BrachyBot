"""Exact title-only catalog write evidence from the current human request.

No model call or tool proposal can grant itself execution. Scope/lease/CAS and
stable target evidence remain enforced by the catalog executor separately.
"""
import re
from collections.abc import Mapping
from agent_runtime.request_parse import parse_request


def explicit_timepoint_title_change(message, params):
    if not isinstance(params, Mapping):
        return False
    action = params.get('action')
    if action == 'rename' and not set(params)-{'action','timepoint_id','title','expected_revision'}:
        title = params.get('title')
    elif action == 'update' and not set(params)-{'action','timepoint_id','patch','expected_revision'}:
        patch = params.get('patch')
        if not isinstance(patch,Mapping) or set(patch) != {'title'}:
            return False
        title = patch.get('title')
    else:
        return False
    if not isinstance(title,str) or not title.strip() or len(title)>160:
        return False
    parsed=parse_request(message)
    for clause in parsed.subtasks:
        if any((clause.negated,clause.conditional,clause.interrogative,
                clause.attributed,clause.completed_action,clause.excluded)):
            continue
        raw=clause.raw
        if not re.search(r'时间点|timepoints?|table\s*viewer',raw,re.IGNORECASE):
            continue
        if not re.search(r'重命名|改名|rename',raw,re.IGNORECASE):
            continue
        # An actual requested title, not an invented provider replacement.
        if title.strip() not in raw:
            continue
        if re.match(r'\s*(?:请|帮我|麻烦|把|将|重命名|改名|please\b|rename\b)',raw,re.IGNORECASE):
            return True
    return False


def requested_implant_observation_operation(message, params):
    """Detection/correction requests do not imply clinical acceptance/review."""
    if not isinstance(params,Mapping):
        return False
    action=params.get('action','detect')
    verbs={
        'detect':r'识别|检测|分割|detect|identify|segment',
        'reconstruct':r'识别|检测|重建|detect|identify|reconstruct',
        'start_add':r'添加|增加|补上|漏检|漏掉|add|missed',
        'add_observation':r'添加|增加|补上|add',
        'start_review':r'复核|审查|review',
        'exclude_observations':r'删除|排除|去掉|误检|误识别|delete|exclude|remove',
        'restore_observations':r'恢复|撤销删除|restore|undo',
        'move_observation':r'移动|调整|微调|更正|move|adjust|correct',
    }
    if action not in verbs:
        return False  # Review acceptance must use its explicit human receipt.
    for clause in parse_request(message).subtasks:
        if any((clause.negated,clause.conditional,clause.interrogative,clause.quoted,
                clause.attributed,clause.completed_action,clause.excluded)):
            continue
        raw=clause.raw
        if not re.search(r'粒子|种子|植入源|seeds?|implanted\s+sources?',raw,re.IGNORECASE):
            continue
        if re.search(verbs[action],raw,re.IGNORECASE) and re.match(
                r'\s*(?:请|帮我|麻烦|把|将|识别|检测|重建|删除|排除|添加|恢复|移动|调整|please\b|detect\b|identify\b|reconstruct\b|delete\b|exclude\b|add\b|restore\b|move\b|adjust\b)',
                raw,re.IGNORECASE):
            return True
    return False
