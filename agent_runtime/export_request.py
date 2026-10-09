"""Structured export proposal validation, independent of human sentence wording.

The proposal opens a chooser only. The user's browser confirmation owns the
actual export. Clinical producers are not substitutes for saving existing data.
"""
import json


def validate_export_dialog_options(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("data.export value must be a selection object")
    allowed = {"all", "object_ids", "group_ids", "data_types", "names", "format", "filenames", "bundle_name", "guide_version",
               "exclude_object_ids", "exclude_group_ids", "exclude_data_types", "exclude_names", "formats_by_object", "formats_by_type"}
    if set(value) - allowed:
        raise ValueError("Unknown export options; paths and automatic confirmation are not supported")
    if "all" in value and not isinstance(value["all"], bool):
        raise ValueError("all must be a boolean")
    if 'guide_version' in value:
        version = value['guide_version']
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise ValueError('guide_version must be a positive integer')
        if value.get('all') or any(value.get(key) for key in ('object_ids', 'group_ids', 'names')) or set(value.get('data_types') or []) - {'surgical_guide'}:
            raise ValueError('guide_version selects one saved guide, not another export scope')
    for key in ("object_ids", "group_ids", "data_types", "names", "exclude_object_ids", "exclude_group_ids", "exclude_data_types", "exclude_names"):
        if key in value and (not isinstance(value[key], list) or len(value[key]) > 512
                or any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in value[key])):
            raise ValueError(f"{key} must be a bounded list of nonempty strings")
    if value.get("all") and any(value.get(key) for key in ("object_ids", "group_ids", "data_types", "names")):
        raise ValueError("Choose an entire Session or a subset, not both")
    for key in ("format", "bundle_name"):
        if key in value and (not isinstance(value[key], str) or not value[key] or len(value[key]) > 120):
            raise ValueError(f"{key} must be a bounded nonempty string")
    names = value.get("filenames", {})
    if not isinstance(names, dict) or len(names) > 512 or any(
            not isinstance(k, str) or not isinstance(v, str) or not v or len(k) > 256 or len(v) > 120
            for k, v in names.items()):
        raise ValueError("filenames must map object IDs to leaf filenames")
    for key in ('formats_by_object', 'formats_by_type'):
        mapping = value.get(key, {})
        if not isinstance(mapping, dict) or len(mapping) > 512 or any(
                not isinstance(k, str) or not isinstance(v, str) or not k or not v or len(k) > 256 or len(v) > 120 for k, v in mapping.items()):
            raise ValueError(f'{key} must map catalog identities to format names')
    return json.loads(json.dumps(value, allow_nan=False))


def export_dialog_requested(message):
    from agent_runtime.request_parse import parse_request, _subtask_can_authorize
    return any(_subtask_can_authorize(task) and not task.excluded
               and "export" in (task.actions or (task.action,))
               for task in parse_request(message).subtasks)


def is_export_dialog_action(action):
    return isinstance(action, dict) and action.get("target") in {"data.export", "report.export"} and action.get("command") == "run"
