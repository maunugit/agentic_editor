"""Data models (containers) for the agentic editor change report and edit operations.
Plain lightweight Python dataclasses that generate all the boilerplate stuff.
Used to auto-generate __init__, __repr__, etc. from the field definitions.
The data models specify what recording and reporting looks like.
These objects don't do any editing themselves.
"""

from dataclasses import dataclass, field
from enum import Enum


class OperationType(Enum):
    """Types of edit operations the agent can perform."""

    REPLACE = "replace"
    DELETE = "delete"
    ADD = "add"


@dataclass
class ChangeEntry:
    """A single recorded edit operation.

    Attributes:
        line_numbers: The line number(s) affected by this edit.
        operation: The type of edit (replace, delete, add).
        before: The original content of the affected lines, captured from the
            actual file text (not LLM output).
        after: The new content after the edit, captured from the actual file
            text. Empty string for delete operations.
        reason: A short audit-label explanation for why this edit was made.
    """
    # These need to be provided by the caller. No default values exist.
    # The type annotations tell Python what each field should be. 
    # @dataclass reads these and generates an __init__ that thakes them all as arguments
    line_numbers: list[int]
    operation: OperationType
    before: str
    after: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "line_numbers": self.line_numbers,
            "operation": self.operation.value,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
        }


@dataclass
class ChangeReport:
    """Structured report of all changes made during an editing session.

    Attributes:
        changes: List of individual change entries recorded during editing.
    """

    # The field "changes" is a list of ChangeEntry. If nobody provides one, it creates a new empty list.
    # The line field(default_factory=list) is used instead of ->
    # changes: list[ChangeEntry] = [] because every instance of ChangeReport would then share ->
    # the same list object... Adding a change to one report would add it to all of them.
    # The default_factory=list calls the list() object every time to create a fresh list per instance.
    changes: list[ChangeEntry] = field(default_factory=list)

    # Just modifies the internal list by appending the change
    def add_change(self, change: ChangeEntry) -> None:
        self.changes.append(change)

    # Produces a dict representation of the data from changes
    def to_dict(self) -> dict:
        # shorthand for a loop to append c to result from self.changes
        # self.changes is a list of ChangeEntry objects. Each ChangeEntry also has its own to_dict()
        return {"changes": [c.to_dict() for c in self.changes]} 


@dataclass
class EditResult:
    """The final result returned by the editing agent.

    Attributes:
        content: The edited file content as a string.
        report: The structured change report (None if reporting was disabled).
        status: Final agent status for this run.
        final_message: Final model or runtime message describing completion or failure.
        completed: Whether the agent completed successfully.
    """

    content: str
    report: ChangeReport | None = None
    status: str = "done"
    final_message: str | None = None
    completed: bool = True
