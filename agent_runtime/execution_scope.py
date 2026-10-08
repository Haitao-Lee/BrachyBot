"""Immutable current-human effect ceiling, independent of tool selection.

The primary model still interprets the full utterance and proposes actions.
This small structural guard can only deny side effects. It cannot authorize
one, add work, infer clinical thresholds, or use history as permission.
"""
from dataclasses import dataclass
import hashlib
from typing import FrozenSet, Optional

from agent_runtime.request_parse import parse_request, tool_authorization_target


def operation_effects(tool, params=None):
    """Server-owned capability effects, not a natural-language command list."""
    goal = tool_authorization_target(tool)
    if goal:
        return frozenset({goal[0]})
    if tool == 'ui_controller':
        effects = set()
        for action in (params or {}).get('actions', ()):
            if not isinstance(action, dict):
                return frozenset({'unknown'})
            target = str(action.get('target') or '')
            if target.startswith('report.'):
                effects.add('report')
            elif target.startswith(('manual.plan.', 'plan.')):
                effects.add('planning')
            elif target.startswith('surgical_guide.'):
                effects.add('surgical_guide')
            elif target.startswith(('viewer.', 'tree.')):
                effects.add('viewer')
            else:
                effects.add('unknown')
        return frozenset(effects or {'unknown'})
    return frozenset({'unknown'})


@dataclass(frozen=True)
class ExecutionScope:
    request_sha256: str = ''
    excluded: FrozenSet[str] = frozenset()
    exclusive: Optional[FrozenSet[str]] = None
    partial: FrozenSet[str] = frozenset()

    @classmethod
    def from_request(cls, message):
        raw = str(message or '')
        parsed = parse_request(raw)
        return cls(hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                   frozenset(parsed.excluded_targets), parsed.exclusive_write_targets,
                   parsed.partial_write_targets)

    def allows(self, tool, params=None):
        effects = operation_effects(tool, params)
        if effects & self.excluded:
            return False
        if effects & self.partial:
            # Whole-object producers cannot implement a part-only write.
            # Only registered field-targeted UI mutations may do so; their
            # action/field/value remains subject to the normal UI validator.
            if tool != 'ui_controller':
                return False
            for action in (params or {}).get('actions', ()):
                target = str(action.get('target') or '')
                if target.startswith('report.') and target != 'report.field.set':
                    return False
                if not target.startswith('report.'):
                    return False
        if self.exclusive is None:
            return True
        # Only missing INPUT masks may be derived from a planning operation.
        # They never override a prohibition. Dose/DVH inside the atomic
        # planning pipeline are its own output, not optional follow-up calls.
        allowed = set(self.exclusive)
        if 'planning' in allowed:
            allowed.update({'ctv', 'oar', 'structure'})
        return effects.issubset(allowed)

    def to_dict(self):
        return {'request_sha256': self.request_sha256,
                'excluded_effects': sorted(self.excluded),
                'exclusive_effects': sorted(self.exclusive) if self.exclusive is not None else None,
                'partial_effects': sorted(self.partial),
                'grants_execution': False}


def check_call_scopes(calls, authorization):
    """Keep a refused proposal visible; never silently lose a sibling goal."""
    if authorization is None:
        return list(calls)
    result = []
    for call in calls:
        if call.get('_argument_error') or authorization.effect_allowed(call.get('tool', ''), call.get('params') or {}):
            result.append(call)
        else:
            result.append(dict(call, _argument_error=(
                'This operation exceeds the current human request scope and was not executed. '
                'Continue the independently authorized outcomes. Do not ask to confirm an '
                'explicitly excluded or optional follow-up, and do not retry it unchanged.'),
                _admission_denied=True, _admission_code='request_scope'))
    return result
