"""Integration tests that call the live Gemini API.

Skipped when GEMINI_API_KEY is not set.
"""

import os

import pytest

from agentic_editor import edit_file, OperationType

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


async def test_simple_replace():
    """Replace a specific word on one line only."""
    content = "Hello world\nGoodbye world"
    result = await edit_file(
        instruction='Replace "world" with "Earth" on the first line only.',
        content=content,
    )
    # Content assertions
    assert "Hello Earth" in result.content
    assert "Goodbye world" in result.content

    # Report assertions
    assert result.report is not None
    assert len(result.report.changes) >= 1
    change = result.report.changes[0]
    assert change.operation == OperationType.REPLACE
    assert change.before == "Hello world"
    assert change.after == "Hello Earth"
    assert change.reason != ""


async def test_delete_line():
    """Delete a line identified by its content."""
    content = "line one\nDELETE ME\nline three"
    result = await edit_file(
        instruction='Delete the line that says "DELETE ME".',
        content=content,
    )
    # Content assertions
    assert "DELETE ME" not in result.content
    assert "line one" in result.content
    assert "line three" in result.content

    # Report assertions
    assert result.report is not None
    assert len(result.report.changes) >= 1
    change = result.report.changes[0]
    assert change.operation == OperationType.DELETE
    assert change.before == "DELETE ME"
    assert change.after == ""
    assert change.reason != ""


async def test_add_line():
    """Add a new line after a target line."""
    content = "first\nsecond"
    result = await edit_file(
        instruction='Add a line saying "third" after the line that says "second".',
        content=content,
    )
    # Content assertions
    lines = result.content.split("\n")
    assert "third" in lines

    # Report assertions
    assert result.report is not None
    assert len(result.report.changes) >= 1
    change = result.report.changes[0]
    assert change.operation == OperationType.ADD
    assert change.before == ""
    assert change.after == "third"
    assert change.reason != ""


async def test_no_changes_needed():
    """Handle instructions where the target text doesn't exist in the file."""
    content = "Hello world"
    result = await edit_file(
        instruction='Replace "xyz123_nonexistent" with "abc" wherever it appears.',
        content=content,
    )
    # Content should be unchanged since the target doesn't exist
    assert "Hello world" in result.content

    # Report should exist but be empty — no edits were made
    assert result.report is not None
    assert len(result.report.changes) == 0


# ── Format-specific tests ───────────────────────────────────────────────────


async def test_json_fix_value():
    """Fix a wrong value in a JSON file."""
    content = '{\n  "title": "The Solar System",\n  "planet_count": 7,\n  "star": "The Sun"\n}'
    result = await edit_file(
        instruction='The planet_count is wrong. Change the value from 7 to 8.',
        content=content,
    )
    # Content assertions
    assert '"planet_count": 8' in result.content
    assert '"title": "The Solar System"' in result.content
    assert '"star": "The Sun"' in result.content

    # Report assertions
    assert result.report is not None
    assert len(result.report.changes) >= 1
    change = result.report.changes[0]
    assert change.operation == OperationType.REPLACE
    assert "7" in change.before
    assert "8" in change.after
    assert change.reason != ""


async def test_json_multiline_fix():
    """Fix multiple issues in a JSON file."""
    content = (
        '{\n'
        '  "course": "Biology 101",\n'
        '  "modules": [\n'
        '    {"id": 1, "title": "Cells", "status": "drafttt"},\n'
        '    {"id": 2, "title": "Genetcs", "status": "draft"},\n'
        '    {"id": 3, "title": "Ecology", "status": "draft"}\n'
        '  ]\n'
        '}'
    )
    result = await edit_file(
        instruction=(
            'Two issues found:\n'
            '1. Module 1 has "drafttt" — fix the typo to "draft"\n'
            '2. Module 2 has "Genetcs" — fix the typo to "Genetics"'
        ),
        content=content,
    )
    # Content assertions
    assert '"drafttt"' not in result.content
    assert '"draft"' in result.content
    assert '"Genetcs"' not in result.content
    assert '"Genetics"' in result.content

    # Report assertions — 2 changes, search by before content since order may vary
    assert result.report is not None
    assert len(result.report.changes) >= 2
    befores = [c.before for c in result.report.changes]
    afters  = [c.after  for c in result.report.changes]
    assert any("drafttt" in b for b in befores)
    assert any("draft"   in a and "drafttt" not in a for a in afters)
    assert any("Genetcs" in b for b in befores)
    assert any("Genetics" in a for a in afters)
    assert all(c.operation == OperationType.REPLACE for c in result.report.changes)
    assert all(c.reason != "" for c in result.report.changes)


async def test_html_fix_content():
    """Fix content errors in an HTML file."""
    content = (
        "<html>\n"
        "<head><title>Solar System</title></head>\n"
        "<body>\n"
        "  <h1>The Solar Sytem</h1>\n"
        "  <p>There are 7 planets in our solar system.</p>\n"
        "  <p>The largest planet is Saturn.</p>\n"
        "</body>\n"
        "</html>"
    )
    result = await edit_file(
        instruction=(
            "Three issues found:\n"
            '1. "Solar Sytem" in the h1 tag is a typo — fix to "Solar System"\n'
            '2. There are 8 planets, not 7\n'
            '3. The largest planet is Jupiter, not Saturn'
        ),
        content=content,
    )
    # Content assertions
    assert "Solar Sytem" not in result.content
    assert "Solar System" in result.content
    assert "7 planets" not in result.content
    assert "8 planets" in result.content
    assert "Saturn" not in result.content
    assert "Jupiter" in result.content

    # Report assertions — 3 changes, search by before content
    assert result.report is not None
    assert len(result.report.changes) >= 3
    befores = [c.before for c in result.report.changes]
    assert any("Solar Sytem" in b for b in befores)
    assert any("7 planets"   in b for b in befores)
    assert any("Saturn"      in b for b in befores)
    assert all(c.operation == OperationType.REPLACE for c in result.report.changes)
    assert all(c.reason != "" for c in result.report.changes)


async def test_markdown_fix_and_delete():
    """Fix a typo and remove a line in a Markdown file."""
    content = (
        "# Introduction to Pyhton\n"
        "\n"
        "Python is a popular programming language.\n"
        "TODO: REMOVE THIS LINE BEFORE PUBLISHING\n"
        "\n"
        "## Features\n"
        "\n"
        "- Easy to learn\n"
        "- Versatile\n"
    )
    result = await edit_file(
        instruction=(
            '1. The heading has "Pyhton" — fix to "Python"\n'
            '2. Remove the line that says "TODO: REMOVE THIS LINE BEFORE PUBLISHING"'
        ),
        content=content,
    )
    # Content assertions
    assert "Pyhton" not in result.content
    assert "# Introduction to Python" in result.content
    assert "TODO: REMOVE THIS LINE" not in result.content
    assert "- Easy to learn" in result.content

    # Report assertions — 1 replace + 1 delete
    assert result.report is not None
    assert len(result.report.changes) >= 2
    operations = [c.operation for c in result.report.changes]
    befores    = [c.before    for c in result.report.changes]
    assert OperationType.REPLACE in operations
    assert OperationType.DELETE  in operations
    assert any("Pyhton" in b for b in befores)
    assert any("TODO"   in b for b in befores)
    # The delete entry must have empty after
    delete_change = next(c for c in result.report.changes if c.operation == OperationType.DELETE)
    assert delete_change.after == ""
    assert all(c.reason != "" for c in result.report.changes)
