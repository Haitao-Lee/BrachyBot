"""Evaluator-side entry contract. This is not an OS/hostile-adapter sandbox.

Only browser input + Send is a formal product evaluation. Model callbacks,
chat_with_trace, synthetic scenes and replay remain useful component tests.
Receipts are collected by the harness, never accepted from a model answer.
"""
from __future__ import annotations

import hashlib

ENTRY_MODE = "browser_user_chat"
CONTRACT_VERSION = "1.0"


class UserChatBlocked(RuntimeError):
    def __init__(self, message, *, observation=None):
        super().__init__(message)
        self.observation = observation


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def user_turns(task):
    """Do not flatten privileged/system/tool messages into user commands."""
    turns = (task.get("protocol") or {}).get("turns") or []
    if not turns:
        raise UserChatBlocked("no user dialogue supplied")
    for turn in turns:
        if turn.get("role") != "user":
            raise UserChatBlocked("non-user protocol turns require a separate UI/environment fixture driver")
        if not isinstance(turn.get("text"), str) or not turn["text"].strip():
            raise UserChatBlocked("empty/non-text user input")
        if turn.get("attachments") or turn.get("images") or turn.get("image_path"):
            raise UserChatBlocked("actual UI attachment upload driver required; text-only driver cannot omit images")
    return turns


def evidence_errors(evidence, task):
    """Check input identity, isolation and browser-side terminal ownership."""
    errors = []
    if not isinstance(evidence, dict):
        return ["user_chat_execution_evidence_missing"]
    if evidence.get("entry_mode") != ENTRY_MODE or evidence.get("contract_version") != CONTRACT_VERSION:
        errors.append("wrong_execution_entry")
    if evidence.get("isolated_workspace") is not True or not evidence.get("session_id"):
        errors.append("isolated_workspace_not_verified")
    if not evidence.get("execution_id"):
        errors.append("execution_identity_missing")
    try:
        turns = user_turns(task)
    except UserChatBlocked as exc:
        return errors + [str(exc)]
    receipts = evidence.get("turns") or []
    if len(receipts) != len(turns):
        errors.append("user_turn_count_mismatch")
    seen = set()
    for turn, receipt in zip(turns, receipts):
        if not isinstance(receipt, dict):
            errors.append("malformed_browser_receipt")
            continue
        if receipt.get("input_sha256") != text_hash(turn["text"].strip()):
            errors.append("submitted_input_mismatch")
        if receipt.get("session_id") != evidence.get("session_id"):
            errors.append("case_session_mismatch")
        if receipt.get("input_action") != "fill_chatInput_click_chatSendBtn":
            errors.append("browser_input_action_missing")
        identity = receipt.get("request_id")
        if not identity or identity in seen:
            errors.append("missing_or_reused_request_identity")
        seen.add(identity)
        if receipt.get("network_message_sha256") != receipt.get("input_sha256"):
            errors.append("ordinary_user_request_not_observed")
        if receipt.get("internal_followup") is not False:
            errors.append("user_turn_replaced_by_internal_followup")
        if receipt.get("browser_settled") is not True or receipt.get("final_rendered") is not True:
            errors.append("browser_final_delivery_not_verified")
        if receipt.get("final_message_count") != 1:
            errors.append("non_unique_final_message")
        if not receipt.get("user_message_id") or not receipt.get("assistant_message_id"):
            errors.append("message_identity_missing")
        if receipt.get("user_echo_sha256") != receipt.get("input_sha256"):
            errors.append("user_echo_mismatch")
    return sorted(set(errors))


class UserChatHandle:
    """External-adapter bridge with an explicitly reviewed public serializer.

The serializer sees only the external adapter's public observation. It must
produce user text, not injected assistant/tool roles. Sessions are evaluator-
prepared isolated browser sessions. The source scorer remains independent.
"""
    entry_mode = ENTRY_MODE

    def __init__(self, session, serializer):
        # Import here to keep scorer/data imports free of browser machinery.
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent / "brachybench"))
        from tools.adapters.user_chat import BrowserChatSession
        if not isinstance(session, BrowserChatSession):
            raise UserChatBlocked("external handle requires a BrowserChatSession")
        self.session = session
        self.serializer = serializer
        self.receipts = []
        self.submitted_texts = []

    def __call__(self, public_observation):
        text = self.serializer(public_observation)
        if not isinstance(text, str) or not text.strip():
            raise UserChatBlocked("serializer must return a nonempty user message")
        result = self.session.submit(text)
        proof = {"contract_version": CONTRACT_VERSION, "entry_mode": ENTRY_MODE,
                 "execution_id": self.session.execution_id, "session_id": self.session.session_id,
                 "isolated_workspace": self.session.isolated_workspace,
                 "turns": [result["entry_receipt"]]}
        errors = evidence_errors(proof, {"protocol": {"turns": [{"role": "user", "text": text}]}})
        if errors:
            raise UserChatBlocked(", ".join(errors))
        self.receipts.append(result["entry_receipt"])
        self.submitted_texts.append(text)
        return {"text": result["response"], "response": result["response"],
                "trace": result.get("trace", []), "partial_status": result.get("partial_status", "PARTIAL")}

    def execution_evidence(self):
        return {"contract_version": CONTRACT_VERSION, "entry_mode": ENTRY_MODE,
                "execution_id": self.session.execution_id, "session_id": self.session.session_id,
                "isolated_workspace": self.session.isolated_workspace, "turns": list(self.receipts)}
