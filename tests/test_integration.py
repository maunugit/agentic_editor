"""Integration tests that call the live Gemini API.

These tests are opt-in because they require both a valid GEMINI_API_KEY and
real network access to the Gemini API.
"""

import os

import pytest

from agentic_editor import edit_file

pytestmark = pytest.mark.skipif(
    (
        not os.environ.get("GEMINI_API_KEY")
        or os.environ.get("RUN_GEMINI_INTEGRATION_TESTS") != "1"
    ),
    reason=(
        "Live Gemini integration tests require GEMINI_API_KEY and "
        "RUN_GEMINI_INTEGRATION_TESTS=1"
    ),
)


def _assert_successful_result(result) -> None:
    assert result.completed is True
    assert result.status == "done"
    assert result.final_message is not None
    assert result.final_message.startswith("DONE:")


async def test_simple_replace():
    """Replace a specific word on one line only."""
    content = "Hello world\nGoodbye world"
    result = await edit_file(
        instruction='Replace "world" with "Earth" on the first line only.',
        content=content,
    )
    assert "Hello Earth" in result.content
    assert "Goodbye world" in result.content
    _assert_successful_result(result)
    assert result.report is not None
    assert len(result.report.changes) >= 1


async def test_delete_line():
    """Delete a line identified by its content."""
    content = "line one\nDELETE ME\nline three"
    result = await edit_file(
        instruction='Delete the line that says "DELETE ME".',
        content=content,
    )
    assert "DELETE ME" not in result.content
    assert "line one" in result.content
    assert "line three" in result.content
    _assert_successful_result(result)


async def test_add_line():
    """Add a new line after a target line."""
    content = "first\nsecond"
    result = await edit_file(
        instruction='Add a line saying "third" after the line that says "second".',
        content=content,
    )
    lines = result.content.split("\n")
    assert "third" in lines
    _assert_successful_result(result)


async def test_report_disabled_still_edits_content():
    """A successful edit should work normally when report generation is disabled."""
    content = "The heading says Pyhton."
    result = await edit_file(
        instruction='Replace "Pyhton" with "Python".',
        content=content,
        report=False,
    )
    assert result.content == "The heading says Python."
    _assert_successful_result(result)
    assert result.report is None


async def test_no_changes_needed():
    """Handle instructions where the target text doesn't exist in the file."""
    content = "Hello world"
    result = await edit_file(
        instruction='Replace "xyz123_nonexistent" with "abc" wherever it appears.',
        content=content,
    )
    # Content should be unchanged since the target doesn't exist
    assert "Hello world" in result.content
    assert result.status in {"done", "error"}
    assert result.completed is (result.status == "done")


# ── Format-specific tests ───────────────────────────────────────────────────


async def test_json_fix_value():
    """Fix a wrong value in a JSON file."""
    content = '{\n  "title": "The Solar System",\n  "planet_count": 7,\n  "star": "The Sun"\n}'
    result = await edit_file(
        instruction='The planet_count is wrong. Change the value from 7 to 8.',
        content=content,
    )
    assert '"planet_count": 8' in result.content
    # Other fields should be untouched
    assert '"title": "The Solar System"' in result.content
    assert '"star": "The Sun"' in result.content
    _assert_successful_result(result)


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
    assert '"drafttt"' not in result.content
    assert '"draft"' in result.content
    assert '"Genetcs"' not in result.content
    assert '"Genetics"' in result.content
    _assert_successful_result(result)
    assert result.report is not None
    assert len(result.report.changes) >= 2


async def test_json_ambiguous_target_requires_local_context():
    """The agent should disambiguate repeated matching lines using nearby context."""
    content = (
        '{\n'
        '  "modules": [\n'
        '    {\n'
        '      "id": 101,\n'
        '      "title": "Introduction"\n'
        '    },\n'
        '    {\n'
        '      "id": 102,\n'
        '      "title": "Introduction"\n'
        '    },\n'
        '    {\n'
        '      "id": 103,\n'
        '      "title": "Summary"\n'
        '    }\n'
        '  ]\n'
        '}'
    )
    result = await edit_file(
        instruction=(
            'In the module where "id": 102, change the title from '
            '"Introduction" to "Deep Dive". Do not change the other title lines.'
        ),
        content=content,
    )
    assert '"id": 101' in result.content
    assert '"id": 102' in result.content
    assert '"title": "Deep Dive"' in result.content
    assert result.content.count('"title": "Introduction"') == 1
    _assert_successful_result(result)


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
    assert "Solar Sytem" not in result.content
    assert "Solar System" in result.content
    assert "7 planets" not in result.content
    assert "8 planets" in result.content
    assert "Saturn" not in result.content
    assert "Jupiter" in result.content
    _assert_successful_result(result)


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
    assert "Pyhton" not in result.content
    assert "# Introduction to Python" in result.content
    assert "TODO: REMOVE THIS LINE" not in result.content
    assert "- Easy to learn" in result.content
    _assert_successful_result(result)


async def test_medium_size_markdown_target_in_middle_of_file():
    """A medium-size file should still support a precise retrieval-first edit."""
    sections = []
    for i in range(1, 41):
        sections.append(f"## Lesson {i}")
        if i == 24:
            sections.append("The Pacific Ocean is the smalest ocean on Earth.")
        else:
            sections.append(f"Lesson {i} content is ready for publication.")
        sections.append("")
    content = "\n".join(sections).strip()

    result = await edit_file(
        instruction=(
            'In the section "Lesson 24", replace "smalest" with "smallest". '
            "Do not modify any other lesson sections."
        ),
        content=content,
    )

    assert "The Pacific Ocean is the smalest ocean on Earth." not in result.content
    assert "The Pacific Ocean is the smallest ocean on Earth." in result.content
    assert "Lesson 23 content is ready for publication." in result.content
    assert "Lesson 25 content is ready for publication." in result.content
    _assert_successful_result(result)
