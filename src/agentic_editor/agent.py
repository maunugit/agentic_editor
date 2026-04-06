"""Agent loop logic for the agentic editor.

Sets up the Gemini API client, defines the system prompt and tool declarations,
and implements the agent loop that drives the LLM to perform edits via FileEditor.
"""

import os
import re
from collections.abc import Callable

from google import genai
from google.genai import types

from agentic_editor.models import (
    ChangeEntry,
    ChangeReport,
    EditResult,
    OperationType,
)
from agentic_editor.tools import (
    ContentMismatchError,
    FileEditor,
    InvalidLineRangeError,
    LineNumberError,
    LineRangeTooLargeError,
)

# System prompt

SYSTEM_PROMPT = """\

You are a precise text editor agent.

You are given:
- A file (as text content)
- An editing instruction

Your goal is to apply the instruction accurately by modifying the file step-by-step.

Available tools:
- regex_search(pattern): Find relevant lines using a regex pattern
- replace_line(line_number, new_content, expected_content)
- delete_line(line_number, expected_content)
- add_line(line_number, content)

Workflow:
1. ALWAYS start by using regex_search to locate the correct line(s).
2. NEVER guess line numbers.
3. Perform ONE edit at a time.
4. After each edit, you will receive the updated file content.
5. Use the updated file state for any further operations.

Rules:
- ALWAYS verify content using expected_content when modifying or deleting lines.
- DO NOT modify a line unless you are sure it matches expected_content.
- DO NOT skip steps or combine multiple edits into one.
- DO NOT hallucinate line numbers or content.
- DO NOT explain your reasoning.

Output format:
- When all edits are complete:
  DONE: <brief summary of changes>

- If the instruction is unclear or cannot be executed:
  ERROR: <clear explanation>

- Be precise, safe, and concise. Do not explain your reasoning at length. ocus on executing the instruction.


"""

# Execution-policy constants stay internal for the first redesign pass.
# They tune loop behavior and tool output bounds without widening the public API.
# Maximum turns (each turn = one API call). Prevents infinite loops.
MAX_AGENT_TURNS = 20
MAX_SEARCH_RESULTS = 20
MAX_GET_LINES_RANGE = 20
LINE_PREVIEW_CHARS = 200
MAX_REASON_CHARS = 120

STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_INCOMPLETE_MAX_TURNS = "incomplete_max_turns"
STATUS_INCOMPLETE_MAX_RETRIES = "incomplete_max_retries"
STATUS_PROTOCOL_ERROR = "protocol_error"

TraceCallback = Callable[[dict], None]

# Tool declarations 
# Using FunctionDeclaration (not callables) so the SDK does NOT auto-call them.
# This gives us full control over the agent loop.
# This is basically a trick to control Gemini. We tell it that "these tools exist",
# but don't give Gemini any actual functions to run, because we want full control.
# So instead of the SDK independently executing things during the API connection, 
# Gemini just comes up with "I'd like to call this tool with these args", and hands control back to us.

# https://googleapis.github.io/python-genai/#disabling-automatic-function-calling 
TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration( 
            name="regex_search",
            description=(
                "Search all lines in the file for a regex pattern. "
                "Returns bounded matching results with 1-based line numbers."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "pattern": types.Schema(
                        type="STRING",
                        description="A Python regex pattern to search for.",
                    ),
                },
                required=["pattern"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_line",
            description=(
                "Read the exact content of one line from the current file state. "
                "Use this when search results are ambiguous or you need precise verification."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "line_number": types.Schema(
                        type="INTEGER",
                        description="1-based line number to read.",
                    ),
                },
                required=["line_number"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_lines",
            description=(
                "Read a small contiguous range of lines from the current file state. "
                f"Request at most {MAX_GET_LINES_RANGE} lines at a time."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "start_line": types.Schema(
                        type="INTEGER",
                        description="1-based first line number to read.",
                    ),
                    "end_line": types.Schema(
                        type="INTEGER",
                        description="1-based last line number to read.",
                    ),
                },
                required=["start_line", "end_line"],
            ),
        ),
        types.FunctionDeclaration(
            name="replace_line",
            description=(
                "Replace the content of a specific line. "
                "Provide expected_content to verify the line hasn't changed since you last searched. "
                "Include a short audit-label reason when possible."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "line_number": types.Schema(
                        type="INTEGER",
                        description="1-based line number to replace.",
                    ),
                    "new_content": types.Schema(
                        type="STRING",
                        description="The new text for this line.",
                    ),
                    "expected_content": types.Schema(
                        type="STRING",
                        description="The current content of the line (for verification).",
                    ),
                    "reason": types.Schema(
                        type="STRING",
                        description="Optional short audit-label reason for this edit.",
                    ),
                },
                required=["line_number", "new_content", "expected_content"],
            ),
        ),
        types.FunctionDeclaration(
            name="delete_line",
            description=(
                "Delete a specific line from the file. "
                "Include a short audit-label reason when possible."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "line_number": types.Schema(
                        type="INTEGER",
                        description="1-based line number to delete.",
                    ),
                    "expected_content": types.Schema(
                        type="STRING",
                        description="The current content of the line (for verification).",
                    ),
                    "reason": types.Schema(
                        type="STRING",
                        description="Optional short audit-label reason for this edit.",
                    ),
                },
                required=["line_number", "expected_content"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_line",
            description=(
                "Add a new line after the specified line number. "
                "Use after_line=0 to insert at the beginning of the file. "
                "Include a short audit-label reason when possible."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "after_line": types.Schema(
                        type="INTEGER",
                        description=(
                            "1-based line number to insert after. "
                            "Use 0 to insert before line 1."
                        ),
                    ),
                    "new_content": types.Schema(
                        type="STRING",
                        description="The text for the new line.",
                    ),
                    "reason": types.Schema(
                        type="STRING",
                        description="Optional short audit-label reason for this edit.",
                    ),
                },
                required=["after_line", "new_content"],
            ),
        ),
    ]
)

# Helper functions
def _create_client() -> genai.Client:
    """Create a Gemini API client using the GEMINI_API_KEY env var."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it to your Gemini API key."
        )
    return genai.Client(api_key=api_key)


def _build_user_message(instruction: str, file_content: str) -> str:
    """Build the initial user message with the instruction and compact file metadata."""
    total_lines = len(file_content.split("\n"))
    approximate_chars = len(file_content)
    return (
        f"Instruction: {instruction}\n\n"
        "You do not have the full file contents in context.\n"
        "Use regex_search first, then get_line or get_lines when local context is needed.\n"
        "Always verify the target line content before replacing or deleting.\n\n"
        "File metadata:\n"
        f"- total_lines: {total_lines}\n"
        f"- approximate_chars: {approximate_chars}"
    )


# Agent loop
async def run_agent(
    instruction: str,
    content: str,
    *, # forces everything after to be keyword-only args
    model: str = "gemini-2.5-flash",
    report: bool = True,
    # max_retries now means that it stops on the Nth consecutive tool error. Not "allow N errors and stop on N+1"
    # At 3 retries, the third consecutive tool error ends the run.
    max_retries: int = 3,
    trace_callback: TraceCallback | None = None,
) -> EditResult:
    """Run the agent loop to edit a file based on an instruction.

    Creates a Gemini client, sends the instruction plus compact file metadata to
    the model, and loops: the model calls retrieval or edit tools, we execute
    them on the FileEditor, send back compact tool results, and repeat until the
    model responds with text (DONE/ERROR) or we hit limits.

    Args:
        instruction: Natural-language description of the desired edits.
        content: The plain-text file content to edit.
        model: The Gemini model to use.
        report: Whether to generate a structured change report.
        max_retries: Max consecutive tool errors before giving up.
        trace_callback: Optional callback receiving structured trace events.

    Returns:
        An EditResult with the edited content and optionally a change report.
    """
    client = _create_client() # gemini API connection
    editor = FileEditor(content) # holds the file as a mutable list of lines
    change_report = ChangeReport() if report else None # either a ChangeReport or None
    total_lines = len(content.split("\n"))
    approximate_chars = len(content)

    # Conversation history —> list of Content objects
    # Every message (user&Gemini) gets appended here, and this is sent on every API call
    contents: list[types.Content] = []

    # Initial user message with instruction + compact metadata
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=_build_user_message(instruction, editor.content))],
        )
    )
    _emit_trace_event(
        trace_callback,
        "run_started",
        instruction=instruction,
        model=model,
        report_enabled=report,
        file_metadata={
            "total_lines": total_lines,
            "approximate_chars": approximate_chars,
        },
    )
    # DOCS about this setup
    # https://googleapis.github.io/python-genai/#generate-content 
    config = types.GenerateContentConfig( # Also passed on every API call
        system_instruction=SYSTEM_PROMPT,
        # This passes the schema tools to Gemini so it understands what's available
        tools=[TOOL_DECLARATIONS], # tool menu
        temperature=0.0,  # fully deterministic for editing tasks
    )

    consecutive_errors = 0
    last_error_message: str | None = None

    for _turn in range(MAX_AGENT_TURNS):
        _emit_trace_event(
            trace_callback,
            "turn_started",
            turn=_turn + 1,
        )
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        if not response.candidates:
            result = _build_edit_result(
                editor=editor,
                report=change_report,
                status=STATUS_PROTOCOL_ERROR,
                final_message="Model returned no candidates.",
            )
            _emit_terminal_trace(trace_callback, result)
            return result

        candidate = response.candidates[0]

        if not _has_function_calls(candidate):
            result = _build_terminal_result(
                candidate=candidate,
                editor=editor,
                report=change_report,
            )
            _emit_trace_event(
                trace_callback,
                "model_text_response",
                turn=_turn + 1,
                text=_extract_text_response(candidate),
            )
            _emit_terminal_trace(trace_callback, result)
            return result

        first_function_call = next(
            (
                part.function_call
                for part in candidate.content.parts
                if part.function_call is not None
            ),
            None,
        )
        if first_function_call is None:
            result = _build_edit_result(
                editor=editor,
                report=change_report,
                status=STATUS_PROTOCOL_ERROR,
                final_message=(
                    "Model response was reported as containing a function call, "
                    "but no callable function part was found."
                ),
            )
            _emit_terminal_trace(trace_callback, result)
            return result

        fc = first_function_call
        args = dict(fc.args)
        contents.append(
            types.Content(
                role=getattr(candidate.content, "role", "model"),
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            name=fc.name,
                            args=args,
                        )
                    )
                ],
            )
        )
        _emit_trace_event(
            trace_callback,
            "model_function_call",
            turn=_turn + 1,
            name=fc.name,
            args=args,
        )
        result = _dispatch_tool(editor, fc.name, args, change_report)
        _emit_trace_event(
            trace_callback,
            "tool_result",
            turn=_turn + 1,
            name=fc.name,
            result=result,
        )

        if result["status"] == "error":
            consecutive_errors += 1
            last_error_message = result.get("message")
            if consecutive_errors >= max_retries:
                final_result = _build_edit_result(
                    editor=editor,
                    report=change_report,
                    status=STATUS_INCOMPLETE_MAX_RETRIES,
                    final_message=(
                        "Stopped after reaching the maximum number of consecutive "
                        f"tool errors ({max_retries}). Last error: {last_error_message}"
                    ),
                )
                _emit_terminal_trace(trace_callback, final_result)
                return final_result
        else:
            consecutive_errors = 0
            last_error_message = None

        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response=result,
                        )
                    )
                ],
            )
        )

    result = _build_edit_result(
        editor=editor,
        report=change_report,
        status=STATUS_INCOMPLETE_MAX_TURNS,
        final_message=(
            "Stopped after reaching the maximum number of agent turns "
            f"({MAX_AGENT_TURNS}) before receiving a DONE: or ERROR: response."
        ),
    )
    _emit_terminal_trace(trace_callback, result)
    return result


# Tool dispatch


def _has_function_calls(candidate: types.Candidate) -> bool:
    """Check if a candidate response contains function calls."""
    if not candidate.content or not candidate.content.parts:
        return False
    return any(p.function_call is not None for p in candidate.content.parts)


def _extract_text_response(candidate: types.Candidate) -> str:
    """Extract plain-text content from a candidate response."""
    if not candidate.content or not candidate.content.parts:
        return ""
    texts = [
        part.text.strip()
        for part in candidate.content.parts
        if getattr(part, "text", None)
    ]
    return "\n".join(text for text in texts if text).strip()


def _emit_trace_event(
    callback: TraceCallback | None,
    event_type: str,
    **payload: object,
) -> None:
    """Send a structured trace event to an optional callback."""
    if callback is None:
        return
    callback({"type": event_type, **payload})


def _emit_terminal_trace(
    callback: TraceCallback | None,
    result: EditResult,
) -> None:
    """Emit a standardized terminal trace event for the final result."""
    _emit_trace_event(
        callback,
        "run_finished",
        status=result.status,
        completed=result.completed,
        final_message=result.final_message,
        content=result.content,
        report=result.report.to_dict() if result.report is not None else None,
    )


def _build_edit_result(
    *,
    editor: FileEditor,
    report: ChangeReport | None,
    status: str,
    final_message: str | None,
) -> EditResult:
    """Build a standardized EditResult for any terminal state."""
    return EditResult(
        content=editor.content,
        report=report,
        status=status,
        final_message=final_message,
        completed=status == STATUS_DONE,
    )


def _build_terminal_result(
    *,
    candidate: types.Candidate,
    editor: FileEditor,
    report: ChangeReport | None,
) -> EditResult:
    """Convert a text-only model response into an explicit terminal result."""
    text = _extract_text_response(candidate)

    if text.startswith("DONE:"):
        return _build_edit_result(
            editor=editor,
            report=report,
            status=STATUS_DONE,
            final_message=text,
        )
    if text.startswith("ERROR:"):
        return _build_edit_result(
            editor=editor,
            report=report,
            status=STATUS_ERROR,
            final_message=text,
        )

    message = text or "Model returned an empty non-tool response."
    return _build_edit_result(
        editor=editor,
        report=report,
        status=STATUS_PROTOCOL_ERROR,
        final_message=(
            "Model returned a non-tool response without a valid DONE: or ERROR: "
            f"prefix. Response text: {message}"
        ),
    )


def _dispatch_tool(
    editor: FileEditor,
    name: str,
    args: dict,
    change_report: ChangeReport | None,
) -> dict:
    """Execute a tool call on the FileEditor and return the result as a dict.

    Catches known errors (LineNumberError, ContentMismatchError, re.error)
    and returns them as error dicts so the LLM can retry.
    """
    try:
        if name == "regex_search":
            return _handle_regex_search(editor, args)
        elif name == "get_line":
            return _handle_get_line(editor, args)
        elif name == "get_lines":
            return _handle_get_lines(editor, args)
        elif name == "replace_line":
            return _handle_replace(editor, args, change_report)
        elif name == "delete_line":
            return _handle_delete(editor, args, change_report)
        elif name == "add_line":
            return _handle_add(editor, args, change_report)
        else:
            return {"status": "error", "message": f"Unknown tool: {name}"}
    except (
        LineNumberError,
        ContentMismatchError,
        InvalidLineRangeError,
        LineRangeTooLargeError,
        ToolArgumentError,
    ) as e:
        return {"status": "error", "message": str(e)}
    except (KeyError, TypeError, ValueError) as e:
        return {"status": "error", "message": f"Invalid tool arguments: {e}"}
    except re.error as e:
        return {"status": "error", "message": f"Invalid regex pattern: {e}"}


def _handle_regex_search(editor: FileEditor, args: dict) -> dict:
    """Execute a regex search and return matches."""
    result = editor.regex_search(
        _require_str_arg(args, "pattern"),
        max_results=MAX_SEARCH_RESULTS,
        preview_chars=LINE_PREVIEW_CHARS,
    )
    if not result.matches:
        return {
            "status": "success",
            "matches": [],
            "message": "No matches found.",
            "total_matches": 0,
            # truncated means that the tool found more results than it returned. max_results = 20
            # if it found 40 results, it only shows the 20. But truncated = true means that there is more than shown
            # full logic in tools.py lines ~130+
            "truncated": False, 
        }
    return {
        "status": "success",
        "matches": [
            {
                "line_number": m.line_number,
                "line_content": m.line_content,
                "match_text": m.match_text,
            }
            for m in result.matches
        ],
        "total_matches": result.total_matches,
        "truncated": result.truncated,
    }


def _handle_get_line(editor: FileEditor, args: dict) -> dict:
    """Read a single line from the current file state."""
    line_number = _require_int_arg(args, "line_number")
    return {
        "status": "success",
        "line_number": line_number,
        "content": editor.get_line(line_number),
    }


def _handle_get_lines(editor: FileEditor, args: dict) -> dict:
    """Read a bounded line range from the current file state."""
    start_line = _require_int_arg(args, "start_line")
    end_line = _require_int_arg(args, "end_line")
    lines = editor.get_lines(start_line, end_line)
    return {
        "status": "success",
        "lines": [
            {"line_number": line.line_number, "content": line.content}
            for line in lines
        ],
    }


def _handle_replace(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line replacement and record the change."""
    line_number = _require_int_arg(args, "line_number")
    new_content = _require_str_arg(args, "new_content")
    expected_content = _require_str_arg(args, "expected_content")
    reason = _resolve_change_reason(
        operation=OperationType.REPLACE,
        provided_reason=_optional_str_arg(args, "reason"),
        before_text=expected_content,
        after_text=new_content,
    )

    before, after = editor.replace(line_number, new_content, expected_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[line_number],
                operation=OperationType.REPLACE,
                before=before,
                after=after,
                reason=reason,
            )
        )

    return {"status": "success", "before": before, "after": after}


def _handle_delete(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line deletion and record the change."""
    line_number = _require_int_arg(args, "line_number")
    expected_content = _require_str_arg(args, "expected_content")
    reason = _resolve_change_reason(
        operation=OperationType.DELETE,
        provided_reason=_optional_str_arg(args, "reason"),
        before_text=expected_content,
    )

    before = editor.delete(line_number, expected_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[line_number],
                operation=OperationType.DELETE,
                before=before,
                after="",
                reason=reason,
            )
        )

    return {"status": "success", "deleted": before}


def _handle_add(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line addition and record the change."""
    after_line = _require_int_arg(args, "after_line")
    new_content = _require_str_arg(args, "new_content")
    reason = _resolve_change_reason(
        operation=OperationType.ADD,
        provided_reason=_optional_str_arg(args, "reason"),
        after_text=new_content,
    )

    editor.add(after_line, new_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[after_line + 1],
                operation=OperationType.ADD,
                before="",
                after=new_content,
                reason=reason,
            )
        )

    return {"status": "success", "added": new_content, "at_line": after_line + 1}


def _normalize_reason_text(text: str) -> str:
    """Normalize a short audit-label reason into a compact single line."""
    collapsed = " ".join(text.split()).strip()
    if len(collapsed) <= MAX_REASON_CHARS:
        return collapsed
    return collapsed[: MAX_REASON_CHARS - 3].rstrip() + "..."


def _preview_reason_text(text: str, *, max_chars: int = 40) -> str:
    """Build a compact preview of line content for deterministic fallback reasons."""
    return _normalize_reason_text(text)[:max_chars].rstrip()


def _resolve_change_reason(
    *,
    operation: OperationType,
    provided_reason: str | None,
    before_text: str | None = None,
    after_text: str | None = None,
) -> str:
    """Resolve a short audit-label reason with deterministic fallback."""
    if provided_reason and provided_reason.strip():
        return _normalize_reason_text(provided_reason)

    if operation == OperationType.REPLACE:
        before_preview = _preview_reason_text(before_text or "")
        after_preview = _preview_reason_text(after_text or "")
        return f"Replace: {before_preview!r} -> {after_preview!r}"
    if operation == OperationType.DELETE:
        before_preview = _preview_reason_text(before_text or "")
        return f"Delete: {before_preview!r}"

    after_preview = _preview_reason_text(after_text or "")
    return f"Add: {after_preview!r}"


def _require_int_arg(args: dict, name: str) -> int:
    """Read a required integer tool argument with a clear error on failure."""
    if name not in args:
        raise ToolArgumentError(f"Missing required argument: {name}")
    value = args[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(
            f"Argument {name} must be an integer, got {type(value).__name__}"
        )
    return value


def _require_str_arg(args: dict, name: str) -> str:
    """Read a required string tool argument with a clear error on failure."""
    if name not in args:
        raise ToolArgumentError(f"Missing required argument: {name}")
    value = args[name]
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"Argument {name} must be a string, got {type(value).__name__}"
        )
    return value


def _optional_str_arg(args: dict, name: str) -> str | None:
    """Read an optional string tool argument with a clear error on failure."""
    if name not in args or args[name] is None:
        return None
    value = args[name]
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"Argument {name} must be a string when provided, got {type(value).__name__}"
        )
    return value


class ToolArgumentError(Exception):
    """Raised when a model tool call provides missing or invalid arguments."""
