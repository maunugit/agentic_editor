"""
Tests for the public API surface.

These tests mock the agent loop so they run without a Gemini API key.
They verify input validation, return types, and the public API contract.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agentic_editor import edit_file, EditResult
from agentic_editor.models import ChangeReport


def _mock_run_agent(content, report):
    """Create a mock run_agent that returns content unchanged."""
    async def fake_run_agent(instruction, content, *, model, report, max_retries):
        change_report = ChangeReport() if report else None
        return EditResult(content=content, report=change_report)
    return fake_run_agent


# calls edit_file() with valid inputs, checks it and returns EditResult
@patch("agentic_editor.agent.run_agent")
async def test_edit_file_returns_edit_result(mock_run):
    mock_run.return_value = EditResult(
        content="some file content", report=ChangeReport()
    )
    result = await edit_file(
        instruction="Fix typos",
        content="some file content",
    )
    assert isinstance(result, EditResult)
    assert result.content == "some file content"
    assert result.report is not None
    mock_run.assert_called_once()


# passes report=False, checks that result.report is None
@patch("agentic_editor.agent.run_agent")
async def test_edit_file_report_disabled(mock_run):
    mock_run.return_value = EditResult(content="some file content", report=None)
    result = await edit_file(
        instruction="Fix typos",
        content="some file content",
        report=False,
    )
    assert result.report is None
    mock_run.assert_called_once()


# These check that empty or blank instructions raise a ValueError
# (validation happens before run_agent is called, so no mock needed)
async def test_edit_file_empty_instruction():
    with pytest.raises(ValueError, match="instruction must not be empty"):
        await edit_file(instruction="", content="some content")


async def test_edit_file_whitespace_instruction():
    with pytest.raises(ValueError, match="instruction must not be empty"):
        await edit_file(instruction="   ", content="some content")


# checks that empty file content raises ValueError
async def test_edit_file_empty_content():
    with pytest.raises(ValueError, match="content must not be empty"):
        await edit_file(instruction="Fix it", content="")
