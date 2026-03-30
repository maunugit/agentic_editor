"""Focused tests for agent helper behavior."""

from types import SimpleNamespace

import pytest

import agentic_editor.agent as agent_module
from agentic_editor.agent import _build_user_message, _dispatch_tool, run_agent
from agentic_editor.tools import FileEditor


def test_build_user_message_uses_compact_metadata_not_full_file():
    content = "first line\nsecond line\nthird line"

    message = _build_user_message("Fix the typo on the second line.", content)

    assert "Instruction: Fix the typo on the second line." in message
    assert "You do not have the full file contents in context." in message
    assert "- total_lines: 3" in message
    assert f"- approximate_chars: {len(content)}" in message
    assert "first line\nsecond line\nthird line" not in message
    assert "1: first line" not in message
    assert "2: second line" not in message
    assert "3: third line" not in message
    assert "File content:" not in message


def test_dispatch_get_line_returns_exact_line_content():
    editor = FileEditor("alpha\nbeta\ngamma")

    result = _dispatch_tool(editor, "get_line", {"line_number": 2}, None)

    assert result == {
        "status": "success",
        "line_number": 2,
        "content": "beta",
    }


def test_dispatch_get_lines_returns_bounded_line_range():
    editor = FileEditor("alpha\nbeta\ngamma")

    result = _dispatch_tool(
        editor,
        "get_lines",
        {"start_line": 2, "end_line": 3},
        None,
    )

    assert result == {
        "status": "success",
        "lines": [
            {"line_number": 2, "content": "beta"},
            {"line_number": 3, "content": "gamma"},
        ],
    }


def test_dispatch_get_lines_returns_error_for_oversized_range():
    editor = FileEditor("\n".join(f"line{i}" for i in range(1, 26)))

    result = _dispatch_tool(
        editor,
        "get_lines",
        {"start_line": 1, "end_line": 21},
        None,
    )

    assert result["status"] == "error"
    assert "exceeds the maximum allowed range" in result["message"]


def test_dispatch_replace_records_model_supplied_audit_label():
    editor = FileEditor("teh cat")
    report = agent_module.ChangeReport()

    result = _dispatch_tool(
        editor,
        "replace_line",
        {
            "line_number": 1,
            "new_content": "the cat",
            "expected_content": "teh cat",
            "reason": "Fix typo: 'teh' -> 'the'",
        },
        report,
    )

    assert result["status"] == "success"
    assert report is not None
    assert len(report.changes) == 1
    assert report.changes[0].reason == "Fix typo: 'teh' -> 'the'"


def test_dispatch_replace_uses_deterministic_reason_fallback():
    editor = FileEditor("teh cat")
    report = agent_module.ChangeReport()

    _dispatch_tool(
        editor,
        "replace_line",
        {
            "line_number": 1,
            "new_content": "the cat",
            "expected_content": "teh cat",
        },
        report,
    )

    assert report is not None
    assert report.changes[0].reason == "Replace: 'teh cat' -> 'the cat'"


def test_dispatch_delete_uses_deterministic_reason_fallback():
    editor = FileEditor("keep\nremove me")
    report = agent_module.ChangeReport()

    _dispatch_tool(
        editor,
        "delete_line",
        {
            "line_number": 2,
            "expected_content": "remove me",
        },
        report,
    )

    assert report is not None
    assert report.changes[0].reason == "Delete: 'remove me'"


def test_dispatch_add_uses_deterministic_reason_fallback():
    editor = FileEditor("first")
    report = agent_module.ChangeReport()

    _dispatch_tool(
        editor,
        "add_line",
        {
            "after_line": 1,
            "new_content": "second",
        },
        report,
    )

    assert report is not None
    assert report.changes[0].reason == "Add: 'second'"


def test_dispatch_replace_returns_error_for_missing_required_arg():
    editor = FileEditor("target")

    result = _dispatch_tool(
        editor,
        "replace_line",
        {
            "line_number": 1,
            "new_content": "fixed target",
        },
        None,
    )

    assert result["status"] == "error"
    assert "Missing required argument: expected_content" in result["message"]


def test_dispatch_get_line_returns_error_for_invalid_arg_type():
    editor = FileEditor("alpha")

    result = _dispatch_tool(
        editor,
        "get_line",
        {"line_number": "not-a-number"},
        None,
    )

    assert result["status"] == "error"
    assert "Argument line_number must be an integer" in result["message"]


def _text_candidate(text: str):
    return SimpleNamespace(
        content=SimpleNamespace(
            parts=[SimpleNamespace(text=text, function_call=None)]
        )
    )


def _function_call_candidate(name: str, args: dict):
    return SimpleNamespace(
        content=SimpleNamespace(
            parts=[
                SimpleNamespace(
                    text=None,
                    function_call=SimpleNamespace(name=name, args=args),
                )
            ]
        )
    )


def _multi_function_call_candidate(calls: list[tuple[str, dict]]):
    return SimpleNamespace(
        content=SimpleNamespace(
            parts=[
                SimpleNamespace(
                    text=None,
                    function_call=SimpleNamespace(name=name, args=args),
                )
                for name, args in calls
            ]
        )
    )


class _FakeResponse:
    def __init__(self, candidate):
        self.candidates = [candidate]


class _FakeModels:
    def __init__(self, responses):
        self._responses = iter(responses)

    async def generate_content(self, **kwargs):
        return _FakeResponse(next(self._responses))


class _FakeClient:
    def __init__(self, responses):
        self.aio = SimpleNamespace(models=_FakeModels(responses))


@pytest.mark.asyncio
async def test_run_agent_returns_done_status_for_done_response(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient([_text_candidate("DONE: replaced the incorrect value")]),
    )

    result = await run_agent(
        instruction="Fix the value",
        content="value = 1",
    )

    assert result.status == "done"
    assert result.completed is True
    assert result.final_message == "DONE: replaced the incorrect value"


@pytest.mark.asyncio
async def test_run_agent_returns_error_status_for_error_response(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient([_text_candidate("ERROR: target line was not found")]),
    )

    result = await run_agent(
        instruction="Delete the missing line",
        content="line one",
    )

    assert result.status == "error"
    assert result.completed is False
    assert result.final_message == "ERROR: target line was not found"


@pytest.mark.asyncio
async def test_run_agent_marks_protocol_error_for_unprefixed_text(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient([_text_candidate("I think I fixed it.")]),
    )

    result = await run_agent(
        instruction="Fix the typo",
        content="teh",
    )

    assert result.status == "protocol_error"
    assert result.completed is False
    assert "valid DONE: or ERROR:" in result.final_message


@pytest.mark.asyncio
async def test_run_agent_marks_incomplete_after_max_retries(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient(
            [
                _function_call_candidate("get_line", {"line_number": 99}),
                _function_call_candidate("get_line", {"line_number": 99}),
            ]
        ),
    )

    result = await run_agent(
        instruction="Read line 99",
        content="only one line",
        max_retries=2,
    )

    assert result.status == "incomplete_max_retries"
    assert result.completed is False
    assert "maximum number of consecutive tool errors (2)" in result.final_message


@pytest.mark.asyncio
async def test_run_agent_executes_only_first_function_call_per_turn(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient(
            [
                _multi_function_call_candidate(
                    [
                        ("add_line", {"after_line": 0, "new_content": "header"}),
                        (
                            "replace_line",
                            {
                                "line_number": 1,
                                "new_content": "fixed target",
                                "expected_content": "target",
                            },
                        ),
                    ]
                ),
                _function_call_candidate(
                    "replace_line",
                    {
                        "line_number": 2,
                        "new_content": "fixed target",
                        "expected_content": "target",
                    },
                ),
                _text_candidate("DONE: inserted header and fixed target"),
            ]
        ),
    )

    result = await run_agent(
        instruction="Insert a header and then fix the target line.",
        content="target",
    )

    assert result.status == "done"
    assert result.completed is True
    assert result.content == "header\nfixed target"
    assert result.report is not None
    assert len(result.report.changes) == 2
    assert result.report.changes[0].operation.value == "add"
    assert result.report.changes[1].operation.value == "replace"


@pytest.mark.asyncio
async def test_run_agent_appends_only_executed_function_call_to_history(monkeypatch):
    recorded_contents = []

    class _RecordingModels:
        def __init__(self, responses):
            self._responses = iter(responses)

        async def generate_content(self, **kwargs):
            recorded_contents.append(kwargs["contents"])
            return _FakeResponse(next(self._responses))

    class _RecordingClient:
        def __init__(self, responses):
            self.aio = SimpleNamespace(models=_RecordingModels(responses))

    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _RecordingClient(
            [
                _multi_function_call_candidate(
                    [
                        ("add_line", {"after_line": 0, "new_content": "header"}),
                        (
                            "replace_line",
                            {
                                "line_number": 1,
                                "new_content": "fixed target",
                                "expected_content": "target",
                            },
                        ),
                    ]
                ),
                _text_candidate("DONE: inserted header"),
            ]
        ),
    )

    result = await run_agent(
        instruction="Insert a header.",
        content="target",
    )

    assert result.status == "done"
    assert len(recorded_contents) == 2
    assert len(recorded_contents[1]) == 3
    model_parts = recorded_contents[1][1].parts
    assert len(model_parts) == 1
    assert model_parts[0].function_call.name == "add_line"


@pytest.mark.asyncio
async def test_run_agent_treats_malformed_tool_args_as_retryable_errors(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient(
            [
                _function_call_candidate(
                    "replace_line",
                    {
                        "line_number": 1,
                        "new_content": "fixed target",
                    },
                ),
                _function_call_candidate(
                    "replace_line",
                    {
                        "line_number": 1,
                        "new_content": "fixed target",
                    },
                ),
            ]
        ),
    )

    result = await run_agent(
        instruction="Fix the target line.",
        content="target",
        max_retries=2,
    )

    assert result.status == "incomplete_max_retries"
    assert result.completed is False
    assert "Missing required argument: expected_content" in result.final_message
    assert result.content == "target"


def test_dispatch_get_line_rejects_stringified_integer_arg():
    editor = FileEditor("alpha")

    result = _dispatch_tool(
        editor,
        "get_line",
        {"line_number": "1"},
        None,
    )

    assert result["status"] == "error"
    assert "Argument line_number must be an integer, got str" in result["message"]


@pytest.mark.asyncio
async def test_run_agent_keeps_partial_audit_trail_on_incomplete_run(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient(
            [
                _function_call_candidate(
                    "replace_line",
                    {
                        "line_number": 1,
                        "new_content": "the cat",
                        "expected_content": "teh cat",
                        "reason": "Fix typo: 'teh' -> 'the'",
                    },
                ),
                _function_call_candidate("get_line", {"line_number": 99}),
                _function_call_candidate("get_line", {"line_number": 99}),
            ]
        ),
    )

    result = await run_agent(
        instruction="Fix the typo and then inspect a missing line",
        content="teh cat",
        max_retries=2,
    )

    assert result.status == "incomplete_max_retries"
    assert result.completed is False
    assert result.content == "the cat"
    assert result.report is not None
    assert len(result.report.changes) == 1
    assert result.report.changes[0].before == "teh cat"
    assert result.report.changes[0].after == "the cat"
    assert result.report.changes[0].reason == "Fix typo: 'teh' -> 'the'"


@pytest.mark.asyncio
async def test_run_agent_marks_incomplete_after_max_turns(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "_create_client",
        lambda: _FakeClient(
            [
                _function_call_candidate("get_line", {"line_number": 1}),
                _function_call_candidate("get_line", {"line_number": 1}),
            ]
        ),
    )
    monkeypatch.setattr(agent_module, "MAX_AGENT_TURNS", 2)

    result = await run_agent(
        instruction="Read the first line repeatedly",
        content="alpha",
    )

    assert result.status == "incomplete_max_turns"
    assert result.completed is False
    assert "maximum number of agent turns (2)" in result.final_message
