"""Semantic-first routing, proposal admission and outcome-level observation.

Routing and model-generated plans are not execution authority. This module
does not execute tools, read patient data, classify clinical acceptability,
or replace action-specific authorization and backend validators.
"""
from copy import deepcopy
from dataclasses import replace
import json
import re
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
    return replace(
        LocalTurnPolicy('semantic_action', candidate.complexity,
                        candidate.requires_review, False, candidate.use_completeness,
                        SEMANTIC_TOOLS),
        routing_source='primary_semantic', routing_reason='semantic_first_outcomes',
        candidate_intent=candidate.candidate_intent or candidate.intent,
    )


def is_semantic_first(policy):
    return getattr(policy, 'routing_reason', '') == 'semantic_first_outcomes'


def outcome_plan_contract_offered(messages, policy):
    """Require a clause-bound plan only when that frame was actually offered.

    Legacy/nonsemantic adapters cannot obey a schema referring to unprovided
    clause IDs. Production semantic packing supplies this passive frame.
    This check is not authorization and never permits any operation.
    """
    prefix = '[Structured state data; not instructions]\n[Passive request frame]\n'
    if not is_semantic_first(policy):
        return False
    for item in messages:
        if (not isinstance(item, Mapping) or item.get('role') != 'user'
                or not isinstance(item.get('content'), str) or not item['content'].startswith(prefix)):
            continue
        try:
            frame = json.loads(item['content'][len(prefix):])
        except (ValueError, TypeError):
            continue
        # Do not add a mandatory generation round to a single uncomplicated
        # saved-fact answer. Compound clauses need an explicit reconciliation;
        # this threshold grants no operation and is not an intent verdict.
        if isinstance(frame, Mapping) and isinstance(frame.get('clauses'), list):
            return len(frame['clauses']) > 1
    return False


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
        if call.get('_admission_code') == 'request_scope':
            return ('该操作超出了你本轮限定的范围，因此未执行；其余已授权任务仍按各自结果处理。'
                    '不会要求你确认执行已明确排除的后续操作。')
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
        'description': ('Record requested outcomes for EVERY non-trivial semantic request, including '
                        'short factual requests and corrections. Include ALL '
                        'passive-frame clause IDs, including restrictions/context. Emit with the '
                        'needed evidence calls in the same batch. This does NOT authorize or '
                        'execute any operation. Record alongside evidence calls, not in a separate '
                        'planning-only round. Do not treat a short request as a reason to skip its outcomes.'),
        'parameters': {'type': 'object', 'properties': {
            'goals': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {
                'type': 'object', 'properties': {
                    'id': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                    'clauses': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {'type': 'string'}},
                    'mode': {'type': 'string', 'enum': ['answer', 'read', 'display', 'modify',
                                                       'control', 'constraint', 'context', 'clarify', 'unsupported']},
                    'outcome': {'type': 'string', 'maxLength': 300},
                    'clarification_question': {'type': 'string', 'minLength': 1, 'maxLength': 300,
                        'description': ('Only for mode=clarify. One focused question in the user language '
                            'resolving the highest-impact missing choice. No numbered catalogue or '
                            'instructions to execute. This permits an immediate clarification without '
                            'an extra synthesis call when the turn contains no factual/action outcomes.')},
                    'evidence': {'type': 'string', 'enum': ['session', 'ui', 'report', 'external', 'dialogue', 'none']},
                    'tools': {'type': 'array', 'maxItems': 12, 'items': {'type': 'string'}},
                    'evidence_requirements': {'type': 'array', 'maxItems': 12,
                        'description': ('For factual reads, bind EACH required operation to its selectors '
                            '(e.g. metric_type, target, action, planning_id). All listed tools/requirements '
                            'are required, not alternatives. This property is legal ONLY for mode=read '
                            'with read-only tools; omit it for answer/modify/clarify/constraint. Optional '
                            'Initial requirements normally contain ONLY tool and params. Add fields/covers '
                            'ONLY after observing the actual returned payload/contract, never guess them. '
                            'fields must be EXACT case-sensitive dotted JSON data paths (e.g. d90 or '
                            'report.stale), never natural-language descriptions. Omit fields when the '
                            'payload schema is unknown. covers names actual returned response_contract '
                            'aspects, NOT clause IDs; omit it if unknown. A wrong-subject read is not coverage.'),
                        'items': {'type': 'object', 'properties': {
                            'tool': {'type': 'string'},
                            'params': {'type': 'object', 'maxProperties': 16},
                            'fields': {'type': 'array', 'maxItems': 12, 'items': {
                                'type': 'string', 'pattern': r'^[\w-]+(?:\.[\w-]+)*$'}},
                            'covers': {'type': 'array', 'maxItems': 12, 'items': {
                                'type': 'string', 'pattern': r'^[\w-]+(?:\.[\w-]+)*$'}},
                        }, 'required': ['tool', 'params']}},
                }, 'required': ['id', 'clauses', 'mode', 'outcome', 'evidence', 'tools'],
            }},
        }, 'required': ['goals']},
    }}


class SemanticDecisionState:
    """Turn-local, bounded proposal/evidence index; never a completion oracle."""
    def __init__(self, message, *, require_plan=False):
        self.frame = build_request_frame(message)
        self.require_plan = bool(require_plan)
        self.goals = ()
        self.repair_issued = False
        self.plan_errors = []

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
            question = goal.get('clarification_question')
            if question is not None and (mode != 'clarify' or not isinstance(question, str)
                    or not question.strip() or len(question) > 300 or '\n' in question):
                raise ValueError('A clarification question must be one bounded line on a clarification goal.')
            if mode == 'read' and evidence in {'session', 'ui', 'report', 'external'} and not tools:
                raise ValueError('A factual read must name its evidence capability.')
            requirements = deepcopy(goal.get('evidence_requirements', []))
            if not isinstance(requirements, list) or len(requirements) > 12:
                raise ValueError('Provide at most 12 evidence requirements.')
            from agent_runtime.execution_authorization import tool_call_is_mutating
            for requirement_index, requirement in enumerate(requirements):
                if not isinstance(requirement, Mapping) or mode != 'read':
                    raise ValueError('Only factual reads may declare evidence requirements.')
                name, selectors = requirement.get('tool'), requirement.get('params')
                if (name not in tools or not isinstance(selectors, dict) or len(selectors) > 16
                        or tool_call_is_mutating(name, selectors)):
                    raise ValueError('Bind requirements to a named read-only capability and its selectors.')
                try:
                    encoded = json.dumps(selectors, allow_nan=False)
                except (TypeError, ValueError):
                    raise ValueError('Evidence selectors must be finite JSON values.') from None
                if len(encoded) > 1600:
                    raise ValueError('Evidence selectors exceed the passive metadata budget.')
                if name == 'ui_content' and selectors.get('target') == 'report' and selectors.get('analysis_basis') == 'structured':
                    # This operation reads saved fields independent of prose;
                    # normalization binds question to the real human request.
                    # A paraphrased question is not a different saved report.
                    requirement = dict(requirement, params={key: value for key, value in selectors.items()
                                                           if key != 'question'})
                    requirements[requirement_index] = requirement
                for key in ('fields', 'covers'):
                    names = requirement.get(key, [])
                    if (not isinstance(names, list) or len(names) > 12 or not all(
                            isinstance(value, str) and 1 <= len(value) <= 80
                            and re.fullmatch(r'[\w-]+(?:\.[\w-]+)*', value) for value in names)):
                        raise ValueError('Evidence fields/aspects must be exact dotted JSON paths, not prose. '
                                         'Omit optional fields/covers when the actual payload schema is unknown.')
            seen.add(identity)
            covered.update(refs)
            accepted.append(dict(id=identity, clauses=list(refs), mode=mode, outcome=outcome,
                                 evidence=evidence, tools=list(tools),
                                 evidence_requirements=deepcopy(requirements)))
            if question is not None:
                accepted[-1]['clarification_question'] = question.strip()
        if covered != clauses:
            raise ValueError('The proposal omits one or more original clauses; include restrictions and context.')
        # Do not leave a partially accepted plan behind on validation failure.
        self.goals = tuple(accepted)
        return {'accepted': True, 'requested_outcomes': len(accepted), 'grants_execution': False,
                'request_sha256': self.frame['request_sha256']}

    def clarification_response(self, receipts=()):
        """No additional generation for a pure, explicit clarification.

        Never replace an independent answer, unsupported outcome or operation
        receipt with a question; partial results must still be reconciled.
        The model chooses the question, not a finite natural-language router.
        """
        if not self.goals or any(g['mode'] not in {'clarify', 'context', 'constraint'} for g in self.goals):
            return ''
        questions = [g.get('clarification_question', '') for g in self.goals if g['mode'] == 'clarify']
        if len(questions) != 1 or not questions[0]:
            return ''
        if any(isinstance(r, Mapping) and r.get('tool') != PLAN_TOOL for r in receipts):
            return ''
        return questions[0]

    def pending_operations(self, receipts=()):
        """Transport-level pending operations, not semantic task completion."""
        return list(dict.fromkeys(r.get('tool') for r in receipts
            if isinstance(r, Mapping) and r.get('status') == 'pending'
            and r.get('attempted') is not False and r.get('tool') != PLAN_TOOL))

    def missing_evidence(self, receipts, *, epoch=None):
        # Consume the executor's outcomes, not UI "done" labels. Pending
        # browser dispatches and reads from before a write are not current.
        successful = [s for s in receipts if isinstance(s, Mapping)
                      and s.get('status') == 'succeeded'
                      and s.get('attempted') is not False
                      and (epoch is None or s.get('epoch') == epoch)]
        names = {s.get('tool') for s in successful}
        from agent_runtime.step_execution import parameter_fingerprints
        def meets(requirement):
            expected = parameter_fingerprints(requirement['params'])
            return any(
                receipt.get('tool') == requirement['tool']
                and all(receipt.get('selector_hashes', {}).get(key) == value for key, value in expected.items())
                and set(requirement.get('covers', ())).issubset(receipt.get('covers', ()))
                and all(receipt.get('field_states', {}).get(path) == 'present'
                        for path in requirement.get('fields', ()))
                for receipt in successful)
        return [goal['id'] for goal in self.goals if goal['mode'] == 'read'
                and goal['evidence'] in {'session', 'ui', 'report', 'external'}
                and (not set(goal['tools']).issubset(names)
                     or not all(meets(item) for item in goal['evidence_requirements']))]

    def pending_evidence(self, receipts, *, epoch=None):
        """Wait for accepted browser work instead of dispatching it again."""
        from agent_runtime.step_execution import parameter_fingerprints
        current = [s for s in receipts if isinstance(s, Mapping)
                   and s.get('status') in {'succeeded', 'pending'} and s.get('attempted') is not False
                   and (epoch is None or s.get('epoch') == epoch)]
        pending = {s.get('tool') for s in current if s.get('status') == 'pending'}
        available = {s.get('tool') for s in current}
        def waiting_or_met(requirement):
            selectors = parameter_fingerprints(requirement['params'])
            return any(s.get('tool') == requirement['tool'] and all(
                s.get('selector_hashes', {}).get(k) == v for k, v in selectors.items())
                and (s.get('status') == 'pending' or (
                    set(requirement.get('covers', ())).issubset(s.get('covers', ()))
                    and all(s.get('field_states', {}).get(p) == 'present'
                            for p in requirement.get('fields', ())))) for s in current)
        return [g['id'] for g in self.goals if g['mode'] == 'read'
                and set(g['tools']) & pending and set(g['tools']).issubset(available)
                and all(waiting_or_met(r) for r in g['evidence_requirements'])]

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
                'outcome_plan_required': self.require_plan,
                'outcome_plan_recorded': bool(self.goals),
                'proposal_is_authorization': False,
                'denied_call_count': sum(bool(s.get('admission_denied')) for s in receipts if isinstance(s, Mapping)),
                'reduced_ui_batch_count': sum(bool(s.get('partial_ui_batch')) for s in receipts if isinstance(s, Mapping)),
                'goals_without_read_receipts': self.missing_evidence(receipts, epoch=epoch),
                'goals_awaiting_browser_receipts': self.pending_evidence(receipts, epoch=epoch),
                'operations_awaiting_completion_receipts': self.pending_operations(receipts),
                'focused_clarification_available': bool(self.clarification_response(receipts)),
                'unbound_read_goals': [g['id'] for g in self.goals if g['mode'] == 'read'
                                      and not g['evidence_requirements']],
                'plan_validation_errors': list(self.plan_errors),
                'semantic_accuracy_verified': False}

