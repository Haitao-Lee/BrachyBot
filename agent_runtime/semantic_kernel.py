"""Semantic-first routing, proposal admission and outcome-level observation.

Routing and model-generated plans are not execution authority. This module
does not execute tools, read patient data, classify clinical acceptability,
or replace action-specific authorization and backend validators.
"""
from copy import deepcopy
from dataclasses import replace
import json
from collections.abc import Mapping
from collections import Counter

from agent_runtime.request_frame import build_request_frame
from agent_runtime.turn_policy import SEMANTIC_TOOLS, LocalTurnPolicy

PLAN_TOOL = 'record_request_plan'


def identify_proposals(calls, batch):
    """Stable identity before normalization, including text-format proposals.

    Two parameter variants of the same tool must not collapse into one call
    when a normalizer drops one. Duplicate explicit identities are refused;
    private receipt identities keep the provider message pairing valid.
    """
    ids = Counter(c.get('id') for c in calls if isinstance(c, Mapping)
                  and isinstance(c.get('id'), str) and c.get('id'))
    used = set(ids)
    result = []
    for index, value in enumerate(calls):
        call = dict(value) if isinstance(value, Mapping) else {
            'tool': 'invalid_tool_call', 'params': {}, '_argument_error': 'Tool proposal must be an object'}
        identity = call.get('id')
        duplicate = isinstance(identity, str) and ids[identity] > 1
        if not isinstance(identity, str) or not identity or duplicate:
            fresh = f'proposal_{batch}_{index}'
            while fresh in used:
                fresh += '_'
            call['id'] = fresh
            used.add(fresh)
        if duplicate:
            call['_argument_error'] = 'Duplicate provider call identity; submit uniquely identified proposals.'
        result.append(call)
    return result


def semantic_runtime_policy(candidate, *, enabled=True, message=None):
    """Use lexical candidates as hints, retaining proved operational shortcuts.

    Whole-command execution contracts, attachment transport and simple
    greetings stay compatible. A general information question no longer
    selects a pre-baked fact packet before the primary model interprets it.
    """
    if not enabled or candidate.intent in {'small_talk', 'visual_analysis', 'external_project_query'}:
        return candidate
    command_only = True
    if message is not None and candidate.intent not in {
        'session_visual_location_query', 'surgical_guide_status_query', 'multi_intent_query',
    }:
        # The legacy "proved" candidate is not infallible. A discussion of
        # an earlier command (e.g. why did you ask me to confirm?) must not
        # inherit a downstream-update shortcut from the quoted action noun.
        from agent_runtime.request_parse import parse_request
        parsed = parse_request(message)
        command_only = not (parsed.interrogative or parsed.conditional or parsed.quoted)
    if candidate.direct_execution and command_only:
        subtasks = candidate.parsed_subtasks or ()
        if candidate.intent != 'multi_intent_query' or all(
            intent in {'session_visual_location_query', 'surgical_guide_status_query'}
            for intent, _ in subtasks
        ):
            return candidate
    if candidate.intent == 'session_content_query':
        return candidate
    return replace(
        LocalTurnPolicy('semantic_action', candidate.complexity,
                        candidate.requires_review, False, candidate.use_completeness,
                        SEMANTIC_TOOLS),
        routing_source='primary_semantic', routing_reason='semantic_first_outcomes',
        candidate_intent=candidate.candidate_intent or candidate.intent,
    )


def is_semantic_first(policy):
    return getattr(policy, 'routing_reason', '') == 'semantic_first_outcomes'


def project_provider_schemas(schemas, policy, metadata=None):
    """Extend with explicitly approved server-side capabilities, not topic words.

    New tools can opt in with conversation_access='read' on the server tool
    object. Unknown extensions are not silently trusted. Inputs are copied;
    cached registry schemas are never narrowed in place.
    """
    if not is_semantic_first(policy):
        return schemas
    allowed = set(SEMANTIC_TOOLS)
    from agent_runtime.execution_authorization import MUTATING_TOOLS
    from utils.tool_security import EXECUTION_TOOLS
    for name, item in (metadata or {}).items():
        if (name not in MUTATING_TOOLS and name not in EXECUTION_TOOLS
                and isinstance(item, Mapping) and item.get('conversation_access') == 'read'):
            allowed.add(name)
    selected = [deepcopy(item) for item in schemas
                if item.get('function', {}).get('name') in allowed]
    # Shared knowledge is not a chat mutation surface. Keep the operation
    # choice explicit instead of advertising an unsafe default action.
    from agent_runtime.execution_authorization import READ_ONLY_ACTIONS
    for item in selected:
        function = item.get('function', {})
        name = function.get('name')
        if name not in {'clinical_kb', 'case_memory', 'surgical_guide'}:
            continue
        parameters = function.get('parameters', {})
        action = parameters.get('properties', {}).get('action')
        if isinstance(action, dict):
            if name == 'clinical_kb' and 'enum' in action:
                action['enum'] = [value for value in action['enum'] if value in READ_ONLY_ACTIONS[name]]
            # A mixed-effect tool must select its operation explicitly; a
            # missing action must not acquire a mutating schema default.
            action.pop('default', None)
            required = parameters.setdefault('required', [])
            if 'action' not in required:
                required.append('action')
    return selected


def admitted_proposals(original, normalized, mounted_names, *, no_ct_tools=(), preserve_notices=False):
    """Return accepted calls AND visible denials, never silent disappearance.

    Normalization/authorization is still authoritative. A rejected call is
    represented with _argument_error so the common execution state emits a
    not-attempted failure receipt and cannot execute it or grant permission.
    """
    mounted = set(mounted_names)
    blocked = set(no_ct_tools)
    accepted = []
    identities = set()
    originals = {c.get('id') or c.get('key') or c.get('tool'): c for c in original}
    for call in normalized:
        call = dict(call)
        prior_notice = call.pop('_partial_ui_batch', None)
        if preserve_notices and isinstance(prior_notice, Mapping):
            call['_partial_ui_batch'] = dict(prior_notice)
        if call.get('_argument_error'):
            accepted.append(call)
        elif call.get('tool') not in mounted or call.get('tool') in blocked:
            call.update(_argument_error='This proposed operation is not available in this turn and was not executed.',
                        _admission_denied=True, _admission_code='unavailable')
            accepted.append(call)
        else:
            proposed = originals.get(call.get('id') or call.get('key') or call.get('tool'), {})
            raw_params = proposed.get('params') or {}
            actual_params = call.get('params') or {}
            raw_actions = raw_params.get('actions') if isinstance(raw_params, Mapping) else None
            actual_actions = actual_params.get('actions') if isinstance(actual_params, Mapping) else None
            if (call.get('tool') == 'ui_controller' and isinstance(raw_actions, list)
                    and isinstance(actual_actions, list) and len(raw_actions) > len(actual_actions)):
                call['_partial_ui_batch'] = {'proposed': len(raw_actions), 'admitted': len(actual_actions)}
            accepted.append(call)
        identities.add(call.get('id') or call.get('key') or call.get('tool'))
    for call in original:
        identity = call.get('id') or call.get('key') or call.get('tool')
        if identity in identities:
            continue
        rejection = dict(call)
        rejection.update(
            _argument_error=('The proposed operation was not admitted by argument, target, scope or '
                             'authorization validation. This operation was not executed; other '
                             'admitted operations have their own receipts. Use an available '
                             'read to resolve the issue, or ask one precise clarification; do not '
                             'retry this same rejected operation unchanged.'),
            _admission_denied=True,
            _admission_code='rejected',
        )
        accepted.append(rejection)
    return accepted


def admission_error_text(call, language='en'):
    """Localize runtime-owned denials; do not reinterpret backend errors."""
    if str(language or '').lower().startswith('zh'):
        if call.get('_admission_code') == 'unavailable':
            return '该操作在本轮不可用，因此未执行。请使用当前可用的读取能力核实所需状态。'
        if call.get('_admission_code') == 'rejected':
            return ('该操作提议未通过参数、目标、范围或授权校验，因此没有执行该项操作；'
                    '其他操作应按各自的执行结果说明。请先读取相关状态，或提出一个明确的澄清问题，'
                    '不要原样重复此提议。')
    return str(call.get('_argument_error') or '')


def partial_batch_notice(call, language='en'):
    batch = call.get('_partial_ui_batch')
    if not isinstance(batch, Mapping):
        return ''
    proposed, admitted = batch['proposed'], batch['admitted']
    if str(language or '').lower().startswith('zh'):
        return (f'\n本次界面操作提议原有 {proposed} 项，校验后的批次包含 {admitted} 项。'
                '执行结果仅对应接受的批次，不能证明原提议的每一项都已执行；'
                '请逐项对照用户需求和实际结果，说明拒绝、合并或仍未解决的部分。')
    return (f'\nThe proposed UI batch had {proposed} entries; the admitted batch has {admitted}. '
            'The execution result applies only to the admitted batch, not independently to '
            'every original entry. Reconcile the user request with actual results, including '
            'rejected, consolidated or unresolved parts.')


def request_plan_schema():
    """Small optional plan, emitted alongside evidence calls in the SAME round."""
    return {'type': 'function', 'function': {
        'name': PLAN_TOOL,
        'description': ('Record requested outcomes for a compound/ambiguous request. Include ALL '
                        'passive-frame clause IDs, including restrictions/context. Emit with the '
                        'needed evidence calls in the same batch. This does NOT authorize or '
                        'execute any operation. Skip for a simple answer.'),
        'parameters': {'type': 'object', 'properties': {
            'goals': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {
                'type': 'object', 'properties': {
                    'id': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                    'clauses': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {'type': 'string'}},
                    'mode': {'type': 'string', 'enum': ['answer', 'read', 'display', 'modify',
                                                       'control', 'constraint', 'context', 'clarify', 'unsupported']},
                    'outcome': {'type': 'string', 'maxLength': 300},
                    'evidence': {'type': 'string', 'enum': ['session', 'ui', 'report', 'external', 'dialogue', 'none']},
                    'tools': {'type': 'array', 'maxItems': 12, 'items': {'type': 'string'}},
                }, 'required': ['id', 'clauses', 'mode', 'outcome', 'evidence', 'tools'],
            }},
        }, 'required': ['goals']},
    }}


class SemanticDecisionState:
    """Turn-local, bounded proposal/evidence index; never a completion oracle."""
    def __init__(self, message):
        self.frame = build_request_frame(message)
        self.goals = ()
        self.repair_issued = False

    def accept(self, params, mounted_names):
        if self.frame['omitted_clause_count'] or any(c['truncated'] for c in self.frame['clauses']):
            raise ValueError('A truncated passive frame cannot prove complete clause coverage.')
        goals = params.get('goals') if isinstance(params, Mapping) else None
        if not isinstance(goals, list) or not 1 <= len(goals) <= 12:
            raise ValueError('Provide 1 to 12 structured outcomes.')
        clauses = {c['id'] for c in self.frame['clauses']}
        seen, covered, accepted = set(), set(), []
        for goal in goals:
            if not isinstance(goal, Mapping):
                raise ValueError('Each outcome must be an object.')
            identity, mode, evidence = goal.get('id'), goal.get('mode'), goal.get('evidence')
            refs, tools = goal.get('clauses'), goal.get('tools')
            outcome = goal.get('outcome')
            if (not isinstance(identity, str) or not identity or len(identity) > 64 or identity in seen
                or mode not in {'answer', 'read', 'display', 'modify', 'control', 'constraint', 'context', 'clarify', 'unsupported'}
                or evidence not in {'session', 'ui', 'report', 'external', 'dialogue', 'none'}
                or not isinstance(outcome, str) or not 1 <= len(outcome) <= 300
                or not isinstance(refs, list) or not 1 <= len(refs) <= 12 or not all(isinstance(x, str) and x in clauses for x in refs)
                or not isinstance(tools, list) or len(tools) > 12 or not all(isinstance(x, str) and x in mounted_names and x != PLAN_TOOL for x in tools)):
                raise ValueError('Invalid outcome identity, clause reference, capability or evidence source.')
            if mode in {'constraint', 'context', 'clarify', 'unsupported'} and tools:
                raise ValueError('A restriction, context or clarification cannot propose an execution.')
            if mode == 'read' and evidence in {'session', 'ui', 'report', 'external'} and not tools:
                raise ValueError('A factual read must name its evidence capability.')
            seen.add(identity)
            covered.update(refs)
            accepted.append(dict(id=identity, clauses=list(refs), mode=mode, outcome=outcome,
                                 evidence=evidence, tools=list(tools)))
        if covered != clauses:
            raise ValueError('The proposal omits one or more original clauses; include restrictions and context.')
        # Do not leave a partially accepted plan behind on validation failure.
        self.goals = tuple(accepted)
        return {'accepted': True, 'requested_outcomes': len(accepted), 'grants_execution': False,
                'request_sha256': self.frame['request_sha256']}

    def missing_evidence(self, receipts, *, epoch=None):
        # Consume the executor's outcomes, not UI "done" labels. Pending
        # browser dispatches and reads from before a write are not current.
        successful = {s.get('tool') for s in receipts if isinstance(s, Mapping)
                      and s.get('status') == 'succeeded'
                      and s.get('attempted') is not False
                      and (epoch is None or s.get('epoch') == epoch)}
        return [goal['id'] for goal in self.goals if goal['mode'] == 'read'
                and goal['evidence'] in {'session', 'ui', 'report', 'external'}
                and not (set(goal['tools']) & successful)]

    def context(self):
        if not self.goals:
            return ''
        return ('\n[Validated outcome proposal; not authority or proof of completion]\n'
                + json.dumps(self.goals, ensure_ascii=False, separators=(',', ':'))
                + '\nBefore answering, reconcile EACH outcome with same-turn receipts and actual '
                  'returned fields. A successful tool is not proof its payload answers the goal. '
                  'Pending browser dispatch is not completion. Respect context/constraint goals; '
                  'never treat them as operations. Report unsupported or unresolved parts precisely.\n')

    def audit(self, receipts=(), *, epoch=None):
        return {'request_sha256': self.frame['request_sha256'], 'planned_goal_count': len(self.goals),
                'proposal_is_authorization': False,
                'denied_call_count': sum(bool(s.get('admission_denied')) for s in receipts if isinstance(s, Mapping)),
                'reduced_ui_batch_count': sum(bool(s.get('partial_ui_batch')) for s in receipts if isinstance(s, Mapping)),
                'goals_without_read_receipts': self.missing_evidence(receipts, epoch=epoch),
                'semantic_accuracy_verified': False}

