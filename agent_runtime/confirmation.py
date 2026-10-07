"""Ephemeral server-owned confirmations; assistant prose is never authority."""
from dataclasses import dataclass
import json
import time

from agent_runtime.execution_authorization import TurnExecutionAuthorization, tool_call_is_mutating


def workspace_fence(memory):
    """No patient arrays, UI claims, file reads or prompt content in the fence."""
    if memory is None:
        return None
    retrieve = getattr(memory, 'retrieve', lambda key: None)
    planning = getattr(memory, 'planning_results', {}) or {}
    versions = getattr(memory, '_planning_versions', {}) or {}
    return (str(getattr(memory, 'session_id', '') or retrieve('session_id') or ''),
            str(retrieve('ct_path') or ''),
            str(planning.get('active_planning_id') or planning.get('planning_run_id') or ''),
            str(planning.get('planning_version', '')),
            tuple(sorted((str(key), str(value)) for key, value in versions.items())))


@dataclass(frozen=True)
class PendingConfirmation:
    payload: str
    fence: tuple
    issued_token: int
    expires_at: float

    @classmethod
    def create(cls, calls, memory, token, now=None):
        calls = [dict(call) for call in calls if isinstance(call, dict)
                 and not call.get('_argument_error')
                 and tool_call_is_mutating(call.get('tool', ''), call.get('params') or {})
                 and call.get('tool') not in {'clinical_kb', 'ui_controller'}]
        if not calls or len(calls) > 8:
            return None
        calls = [{'tool': call['tool'], 'params': call.get('params') or {}} for call in calls]
        try:
            payload = json.dumps(calls, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (ValueError, TypeError):
            return None
        fence = workspace_fence(memory)
        if (len(payload) > 16000 or len(proposal_preview(calls)) > 4000
                or not fence or not any(fence[:2])):
            return None
        return cls(payload, fence, int(token), (time.monotonic() if now is None else now) + 240)

    def consume(self, memory, token, now=None):
        now = time.monotonic() if now is None else now
        if (int(token) != self.issued_token + 1 or now >= self.expires_at
                or workspace_fence(memory) != self.fence):
            return ()
        return tuple(json.loads(self.payload))


def confirmed_operation_allowed(name, params, calls):
    """Reuse the same exact-call boundary as the ordinary execution ledger."""
    ledger = TurnExecutionAuthorization(0)
    ledger.grant_tool_calls(calls or (), source='server_bound_confirmation')
    return ledger.tool_allowed(name, params if isinstance(params, dict) else {})


def proposal_preview(calls):
    """Expose the scoped operation/value, never source paths or secrets."""
    def redact(value):
        if isinstance(value, dict):
            return {key: '[server-resolved input]' if any(term in key.lower()
                    for term in ('path', 'token', 'secret', 'password', 'key')) else redact(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    previews = []
    for call in calls:
        params = redact(call.get('params') or {})
        previews.append({'operation': call['tool'], 'arguments': params})
    # A truncated preview could hide a later operation. Creation rejects an
    # overlong complete preview rather than accepting unseen work.
    return json.dumps(previews, ensure_ascii=False, indent=2)
