"""Tests for the regex tool and edit operations."""

import re

import pytest

from agentic_editor.tools import (
    ContentMismatchError,
    FileEditor,
    InvalidLineRangeError,
    LineNumberError,
    LineRangeTooLargeError,
)


SAMPLE_FILE = """{
  "title": "Water Safety Basics",
  "version": 3,
  "blocks": [
    {"id": 1, "text": "Always swim with a buddy"},
    {"id": 2, "text": "Check water depth before diving"}
  ]
}"""


# FileEditor basics
# Sanity checks that the editor works as a container.
# Content survives a roundtrip (split -> join), line count is correct,
# get_line works with 1-based index, and out-of-range line numbers raise LineNumberError
def test_content_roundtrip():
    editor = FileEditor(SAMPLE_FILE)
    assert editor.content == SAMPLE_FILE

def test_line_count():
    editor = FileEditor(SAMPLE_FILE)
    assert editor.line_count == 8

def test_get_line():
    editor = FileEditor(SAMPLE_FILE)
    assert editor.get_line(1) == "{"
    assert editor.get_line(3) == '  "version": 3,'

def test_get_line_out_of_range():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(LineNumberError):
        editor.get_line(0)
    with pytest.raises(LineNumberError):
        editor.get_line(99)


# Regex search
# Tests four cases: single match, multi-match, zero match, invalid regex pattern.
def test_regex_search_single_match():
    editor = FileEditor(SAMPLE_FILE)
    result = editor.regex_search(r'"version":\s*\d+')
    assert len(result.matches) == 1
    assert result.total_matches == 1
    assert result.truncated is False
    assert result.matches[0].line_number == 3
    assert result.matches[0].match_text == '"version": 3'


def test_regex_search_multiple_matches():
    editor = FileEditor(SAMPLE_FILE)
    result = editor.regex_search(r'"id":\s*\d+')
    assert len(result.matches) == 2
    assert result.total_matches == 2
    assert result.matches[0].line_number == 5
    assert result.matches[1].line_number == 6


def test_regex_search_no_matches():
    editor = FileEditor(SAMPLE_FILE)
    result = editor.regex_search(r"nonexistent_pattern")
    assert result.matches == []
    assert result.total_matches == 0
    assert result.truncated is False


def test_regex_search_invalid_pattern():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(re.error):
        editor.regex_search(r"[invalid")


def test_regex_search_limits_results_and_marks_truncated():
    editor = FileEditor(SAMPLE_FILE)
    result = editor.regex_search(r'"id":\s*\d+', max_results=1)
    assert len(result.matches) == 1
    assert result.total_matches == 2
    assert result.truncated is True
    assert result.matches[0].line_number == 5


def test_regex_search_truncates_line_preview():
    editor = FileEditor(SAMPLE_FILE)
    result = editor.regex_search(
        r'"Check water depth before diving"',
        preview_chars=20,
    )
    assert result.matches[0].line_content.endswith("...")
    assert len(result.matches[0].line_content) == 20


def test_regex_search_rejects_invalid_result_limits():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(ValueError, match="max_results must be at least 1"):
        editor.regex_search(r'"id":\s*\d+', max_results=0)
    with pytest.raises(ValueError, match="preview_chars must be at least 1"):
        editor.regex_search(r'"id":\s*\d+', preview_chars=0)


# Bounded line reads
def test_get_lines_basic():
    editor = FileEditor(SAMPLE_FILE)
    lines = editor.get_lines(2, 4)
    assert [line.line_number for line in lines] == [2, 3, 4]
    assert [line.content for line in lines] == [
        '  "title": "Water Safety Basics",',
        '  "version": 3,',
        '  "blocks": [',
    ]


def test_get_lines_rejects_invalid_range_order():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(InvalidLineRangeError):
        editor.get_lines(4, 2)


def test_get_lines_rejects_out_of_range_bounds():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(LineNumberError):
        editor.get_lines(0, 2)
    with pytest.raises(LineNumberError):
        editor.get_lines(2, 99)


def test_get_lines_rejects_oversized_range():
    editor = FileEditor("\n".join(f"line{i}" for i in range(1, 26)))
    with pytest.raises(LineRangeTooLargeError):
        editor.get_lines(1, 21)


# Replace
# Tests that it returns correct before/after, content verification passing/failing
# Also confirming that the line was NOT changed during content mismatch
def test_replace_basic():
    editor = FileEditor(SAMPLE_FILE)
    before, after = editor.replace(3, '  "version": 4,')
    assert before == '  "version": 3,'
    assert after == '  "version": 4,'
    assert editor.get_line(3) == '  "version": 4,'

def test_replace_with_content_verification():
    editor = FileEditor(SAMPLE_FILE)
    before, after = editor.replace(
        3, '  "version": 4,', expected_content='  "version": 3,'
    )
    assert before == '  "version": 3,'

def test_replace_content_mismatch():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(ContentMismatchError) as exc_info:
        editor.replace(3, '  "version": 4,', expected_content="wrong content")
    assert exc_info.value.line_number == 3
    assert exc_info.value.expected == "wrong content"
    # Ensure the line was NOT changed
    assert editor.get_line(3) == '  "version": 3,'

def test_replace_invalid_line():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(LineNumberError):
        editor.replace(99, "new content")


# Delete
# Tests if deleted content is returned, line count decreases, content verification
def test_delete_basic():
    editor = FileEditor(SAMPLE_FILE)
    original_count = editor.line_count
    deleted = editor.delete(6)
    assert deleted == '    {"id": 2, "text": "Check water depth before diving"}'
    assert editor.line_count == original_count - 1

def test_delete_with_content_verification():
    editor = FileEditor(SAMPLE_FILE)
    deleted = editor.delete(1, expected_content="{")
    assert deleted == "{"

def test_delete_content_mismatch():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(ContentMismatchError):
        editor.delete(1, expected_content="wrong")
    # Ensure the line was NOT deleted
    assert editor.line_count == 8

def test_delete_invalid_line():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(LineNumberError):
        editor.delete(0)


# Add
# Tests inserting after a line, at the beginning (after_line=0), at the end, and invalid pos
def test_add_after_line():
    editor = FileEditor(SAMPLE_FILE)
    original_count = editor.line_count
    editor.add(5, '    {"id": 3, "text": "Wear a life jacket"},')
    assert editor.line_count == original_count + 1
    assert editor.get_line(6) == '    {"id": 3, "text": "Wear a life jacket"},'
    # Original line 6 is now line 7
    assert editor.get_line(7) == '    {"id": 2, "text": "Check water depth before diving"}'


def test_add_at_beginning():
    editor = FileEditor(SAMPLE_FILE)
    editor.add(0, "// header comment")
    assert editor.get_line(1) == "// header comment"
    assert editor.get_line(2) == "{"


def test_add_at_end():
    editor = FileEditor(SAMPLE_FILE)
    editor.add(editor.line_count, "// footer")
    assert editor.get_line(editor.line_count) == "// footer"


def test_add_invalid_line():
    editor = FileEditor(SAMPLE_FILE)
    with pytest.raises(LineNumberError):
        editor.add(-1, "bad")
    with pytest.raises(LineNumberError):
        editor.add(editor.line_count + 1, "bad")


# Line number shifts across sequential edits
# Tests that FileEditor naturally handles shifts because it's just a mutable list
# Delete shifts subsequent lines down
# Add shifts subsequent lines up
# Multiple deletes compound correctly
# A regex search after an edit sees the updated content -> validates the core design that agent gets fresh state
def test_delete_then_replace_shifted():
    """After deleting a line, subsequent line numbers shift down."""
    editor = FileEditor(SAMPLE_FILE)
    # Delete line 5 (first block entry)
    editor.delete(5)
    # What was line 6 is now line 5
    assert editor.get_line(5) == '    {"id": 2, "text": "Check water depth before diving"}'
    # Replace the shifted line
    before, after = editor.replace(5, '    {"id": 2, "text": "Updated safety tip"}')
    assert before == '    {"id": 2, "text": "Check water depth before diving"}'


def test_add_then_replace_shifted():
    """After adding a line, subsequent line numbers shift up."""
    editor = FileEditor(SAMPLE_FILE)
    # Add a line after line 4
    editor.add(4, "    // new comment")
    # Original line 5 is now line 6
    assert editor.get_line(6) == '    {"id": 1, "text": "Always swim with a buddy"},'
    # We can still work with the shifted content
    editor.replace(6, '    {"id": 1, "text": "Updated"},')
    assert editor.get_line(6) == '    {"id": 1, "text": "Updated"},'


def test_multiple_deletes_shift():
    """Multiple deletes shift remaining lines correctly."""
    editor = FileEditor("line1\nline2\nline3\nline4\nline5")
    editor.delete(2)  # remove "line2"
    editor.delete(2)  # now removes "line3" (shifted into position 2)
    assert editor.content == "line1\nline4\nline5"


def test_search_after_edit_reflects_changes():
    """Regex search after an edit should reflect the updated content."""
    editor = FileEditor(SAMPLE_FILE)
    editor.replace(3, '  "version": 10,')
    result = editor.regex_search(r'"version":\s*\d+')
    assert result.matches[0].match_text == '"version": 10'
