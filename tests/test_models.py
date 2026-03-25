"""
Tests for data models.

"""

from agentic_editor.models import (
    ChangeEntry,
    ChangeReport,
    EditResult,
    OperationType,
)

# Checks that the three enum values map to the right strings
# The strings are what end up in the JSON report
def test_operation_type_values():
    assert OperationType.REPLACE.value == "replace"
    assert OperationType.DELETE.value == "delete"
    assert OperationType.ADD.value == "add"

# Creates a fresh ChangeEntry with all fields filled in
# Calls to_dict(), and checks that output is a plain dict with right keys & values
# This is how single edits get serialized into the change report
def test_change_entry_to_dict():
    entry = ChangeEntry(
        line_numbers=[12, 13],
        operation=OperationType.REPLACE,
        before='old content',
        after='new content',
        reason='fix syntax',
    )
    d = entry.to_dict()
    assert d == {
        "line_numbers": [12, 13],
        "operation": "replace",
        "before": "old content",
        "after": "new content",
        "reason": "fix syntax",
    }

# Just a fresh ChangeReport with no changes, should produce []
def test_change_report_empty():
    report = ChangeReport()
    assert report.to_dict() == {"changes": []}

# Creates a ChangeReport, adds one ChangeEntry to it via add_change(),
# then checks if it shows up in the list with the right operation type.
# This verifies that the report accumulates entries as edits happen.
def test_change_report_add_change():
    report = ChangeReport()
    entry = ChangeEntry(
        line_numbers=[5],
        operation=OperationType.DELETE,
        before="removed line",
        after="",
        reason="unnecessary",
    )
    report.add_change(entry)
    assert len(report.changes) == 1
    assert report.to_dict()["changes"][0]["operation"] == "delete"

# EditResult with a report attached has both .content and .report accessible
def test_edit_result_with_report():
    result = EditResult(content="hello", report=ChangeReport())
    assert result.content == "hello"
    assert result.report is not None

# If no report passed, defaults to None. If caller sets report=False
def test_edit_result_without_report():
    result = EditResult(content="hello")
    assert result.report is None
