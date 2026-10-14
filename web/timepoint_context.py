"""Immutable execution read-set, never the browser's currently selected tab."""
from dataclasses import dataclass

from web.timepoints import TimepointConflict, timepoint_id, revision


@dataclass(frozen=True)
class TimepointRead:
    timepoint_id: str
    clinical_revision: int
    stage: str
    preoperative_timepoint_id: str | None
    previous_intraoperative_timepoint_id: str | None
    legacy_default: bool = False
    lifecycle_revision: int = 0

    def __post_init__(self):
        timepoint_id(self.timepoint_id)
        revision(self.clinical_revision)
        revision(self.lifecycle_revision)
        if self.stage not in {"preoperative", "intraoperative"}:
            raise ValueError("Invalid captured stage")
        for item in (self.preoperative_timepoint_id, self.previous_intraoperative_timepoint_id):
            if item is not None:
                timepoint_id(item)


@dataclass(frozen=True)
class TimepointContext:
    owner_id: str
    session_id: str
    target: TimepointRead
    dependencies: tuple = ()

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise ValueError("An execution owner is required")
        timepoint_id(self.session_id)
        if not isinstance(self.target, TimepointRead):
            raise ValueError("A captured target is required")
        deps = tuple(self.dependencies)
        if (any(not isinstance(item, TimepointRead) for item in deps)
                or len({item.timepoint_id for item in deps}) != len(deps)
                or self.target.timepoint_id in {item.timepoint_id for item in deps}):
            raise ValueError("Invalid execution dependency identities")
        object.__setattr__(self, "dependencies", deps)

    def assert_current(self, owner_id, session_id, catalog, *, legacy_revision):
        if self.owner_id != owner_id or self.session_id != session_id:
            raise TimepointConflict("Execution context belongs to another patient or owner")
        for frozen in (self.target, *self.dependencies):
            item = catalog["items"].get(frozen.timepoint_id)
            if not item or item["status"] != "active":
                raise TimepointConflict("Execution target or input dependency is no longer active")
            actual = legacy_revision if item["legacy_default"] else item.get("clinical_revision", 0)
            if (actual != frozen.clinical_revision
                    or item.get("lifecycle_revision", 0) != frozen.lifecycle_revision
                    or bool(item["legacy_default"]) != frozen.legacy_default
                    or item["stage"] != frozen.stage
                    or item.get("preoperative_timepoint_id") != frozen.preoperative_timepoint_id
                    or item.get("previous_intraoperative_timepoint_id") != frozen.previous_intraoperative_timepoint_id):
                raise TimepointConflict("Execution inputs changed; the old result cannot be published as current")


def capture_context(owner_id, session_id, catalog, identifier, legacy_revision):
    seen, pending, rows = set(), [identifier], []
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        item = catalog["items"].get(current)
        if not item or item["status"] != "active":
            raise TimepointConflict("Execution input timepoint is unavailable")
        rows.append(TimepointRead(current,
            legacy_revision if item["legacy_default"] else item.get("clinical_revision", 0),
            item["stage"], item.get("preoperative_timepoint_id"),
            item.get("previous_intraoperative_timepoint_id"), bool(item["legacy_default"]),
            item.get("lifecycle_revision", 0)))
        pending.extend(value for value in (item.get("preoperative_timepoint_id"),
                                          item.get("previous_intraoperative_timepoint_id")) if value)
    return TimepointContext(owner_id, session_id, rows[0], tuple(rows[1:]))
