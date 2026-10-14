"""Compiled inventory of real registered executors and their scope contracts.

An extension can declare server-owned pure/read capability on its tool class.
Neither natural-language wording nor model kwargs can change its contract.
Unknown executors remain visible in the audit with their missing adapter.
"""
from collections.abc import Mapping


def capability_contract(name, tool=None):
    from web.timepoint_chat import SCOPED_CLINICAL_TOOLS, SHARED_READ_TOOLS, BROWSER_TOOLS
    from utils.tool_security import EXECUTION_TOOLS
    if name in EXECUTION_TOOLS:
        return "disabled_developer_execution"
    if name == "timepoint_controller":
        return "catalog_action_adapter"
    if name in SCOPED_CLINICAL_TOOLS:
        return "owned_clinical_adapter"
    if name in BROWSER_TOOLS:
        return "scoped_browser_delivery"
    if name in SHARED_READ_TOOLS:
        return "shared_read_adapter"
    if name == "filesystem_browser":
        return "owned_file_read"
    if name == "case_memory":
        return "owned_experience_read"
    if name == "ui_annotate":
        return "owned_screenshot_annotation"
    access = getattr(tool, "timepoint_access", None)
    if access == "pure" or getattr(tool, "conversation_access", None) == "read":
        return "declared_pure" if access == "pure" else "declared_read"
    return "missing_scope_adapter"


def compiled_capability_catalog(registry, *, browser_ready=False):
    rows = []
    for name in registry.tool_names:
        tool = registry.get(name)
        contract = capability_contract(name, tool)
        enabled = registry.is_available(name) and contract not in {"missing_scope_adapter", "disabled_developer_execution"}
        if contract == "scoped_browser_delivery":
            enabled = enabled and browser_ready
        rows.append({"name": name, "implementation": type(tool).__module__ + "." + type(tool).__name__,
            "scope_contract": contract, "available": bool(enabled),
            "limitation": "missing_scope_adapter" if contract == "missing_scope_adapter" else
                          "browser_scope_delivery_not_installed" if contract == "scoped_browser_delivery" and not browser_ready else None})
    return {"registered_count": len(rows), "tools": rows,
            "missing_scope_adapters": [row["name"] for row in rows if row["scope_contract"] == "missing_scope_adapter"]}
