"""Separate human discourse from tool transport masquerading as user history.

This is provenance bookkeeping, not natural-language intent classification.
Provider evidence and passive state can inform an answer, never become the
current human request or a previous offer to execute an operation.
"""
from collections.abc import Mapping


TRANSPORT_PREFIXES = (
    '[Tool result:', '[Called ', '[External evidence', '[Structured state',
    '[BrachyBot', '[Earlier same-turn tool evidence', '[Reference material;',
    'Visual evidence analysis follow-up.', '[Passive request frame]',
    '[internal:',
)


def dialogue_text(record):
    content = record.get('content', record.get('message', ''))
    if isinstance(content, (list, tuple)):
        content = ' '.join(str(part.get('text') or part.get('content') or '')
                           for part in content if isinstance(part, Mapping)
                           and part.get('type') in {None, 'text', 'input_text'})
    return content if isinstance(content, str) else ''


def is_dialogue_record(record):
    if not isinstance(record, Mapping) or record.get('role') not in {'user', 'assistant'}:
        return False
    if record.get('internal_only') or record.get('internal_followup'):
        return False
    content = dialogue_text(record)
    return bool(content) and not content.lstrip().startswith(TRANSPORT_PREFIXES)


def human_dialogue(conversation):
    return [{**record, 'content': dialogue_text(record)}
            for record in (conversation or ()) if is_dialogue_record(record)]


def latest_human_message(conversation):
    for record in reversed(human_dialogue(conversation)):
        if record['role'] == 'user':
            return record['content']
    return ''
