"""Small, source-owned artifact organization metadata, without moving files."""
from collections.abc import Mapping
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit


def screenshot_attachment_index(snapshot, session_id):
    chat=snapshot.get('chat') if isinstance(snapshot.get('chat'),Mapping) else {}
    candidates=list(chat.get('attachments') or [])
    for message in chat.get('messages') or []:
        if isinstance(message,Mapping):
            candidates.extend(message.get('attachments') or [])
    output={}
    def filename(url):
        path=urlsplit(str(url or '')).path
        match=re.fullmatch(r'/api/sessions/([^/]+)/screenshots/([^/]+)',path)
        if match:
            return match.group(2) if match.group(1)==str(session_id) else None
        legacy=re.fullmatch(r'/api/screenshots/([^/]+)',path)
        return legacy.group(1) if legacy else None
    for attachment in candidates:
        if not isinstance(attachment,Mapping):continue
        owner=str(attachment.get('session_id') or attachment.get('case_id') or '')
        if owner and owner!=str(session_id):continue
        original=filename(attachment.get('original_url') or attachment.get('url'))
        annotated=filename(attachment.get('annotated_url'))
        for name,variant in ((original,'original'),(annotated,'annotated')):
            if not name:continue
            metadata={'artifact_family':'chat_capture','capture_variant':variant,
                      'capture_source_id':str(attachment.get('id') or original or name),
                      'request_id':str(attachment.get('request_id') or ''),
                      'message_id':str(attachment.get('message_id') or ''),
                      'target':str(attachment.get('target') or ''),
                      'created_at':attachment.get('created_at'),
                      'planning_id':attachment.get('planning_id'),
                      'data_version':attachment.get('data_version'),
                      'sha256':attachment.get('annotation_sha256') if variant=='annotated' else attachment.get('sha256')}
            # The top-level registry is authoritative; messages may have old
            # copies. Prefer enriched annotation references over empty data.
            if name not in output:output[name]=metadata
    return output


def legacy_screenshot_metadata(name):
    stem=PurePosixPath(name).stem
    original=re.fullmatch(r'chat_screenshot_([A-Za-z0-9]+)',stem)
    annotated=re.fullmatch(r'annotated_chat_screenshot_([A-Za-z0-9]+)_([A-Za-z0-9]+)',stem)
    if original or annotated:
        return {'artifact_family':'chat_capture', 'capture_source_id':'legacy:'+ (original or annotated).group(1),
                'capture_variant':'annotated' if annotated else 'original',
                'relationship_source':'legacy_generated_filename'}
    return {'artifact_family':'unclassified_image','capture_variant':'saved','relationship_source':'unclassified'}
