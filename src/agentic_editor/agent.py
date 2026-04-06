"""Agent loop logic for the agentic editor.

Sets up the Gemini API client, defines the system prompt and tool declarations,
and implements the agent loop that drives the LLM to perform edits via FileEditor.
"""

import os
import re

from google import genai
from google.genai import types

from agentic_editor.models import (
    ChangeEntry,
    ChangeReport,
    EditResult,
    OperationType,
)
from agentic_editor.tools import ContentMismatchError, FileEditor, LineNumberError

# System prompt

SYSTEM_PROMPT = """\
You are a precise text editor agent. You receive a file and a specific editing instruction.

Your job is to locate the exact lines that need changing using regex_search, \
then apply the edits using replace_line, delete_line, or add_line.

Rules:
- ALWAYS use regex_search first to find the target lines. Never guess line numbers.
- After each edit you will receive the updated file state. Use it for subsequent searches.
- When calling replace_line or delete_line you MUST provide expected_content \
to verify you are editing the correct line.
- Work through one edit at a time. After each tool call, wait for the result before proceeding.
- When you are done with all edits, call finish_editing with status="done" and a brief \
summary of what was changed. Never output plain text to signal completion.
- If the instruction is unclear or impossible to execute, call finish_editing with \
status="error" and an explanation of why.
- Be concise. Do not explain your reasoning at length. Focus on executing the instruction.
"""

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
                "Returns matching lines with their 1-based line numbers."
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
            name="replace_line",
            description=(
                "Replace the content of a specific line. "
                "Provide expected_content to verify the line hasn't changed since you last searched."
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
                        description="Why this edit is being made (e.g. 'fix JSON syntax error').",
                    ),
                },
                required=["line_number", "new_content", "expected_content", "reason"],
            ),
        ),
        types.FunctionDeclaration(
            name="delete_line",
            description="Delete a specific line from the file.",
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
                        description="Why this line is being deleted.",
                    ),
                },
                required=["line_number", "expected_content", "reason"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_line",
            description=(
                "Add a new line after the specified line number. "
                "Use after_line=0 to insert at the beginning of the file."
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
                        description="Why this line is being added.",
                    ),
                },
                required=["after_line", "new_content", "reason"],
            ),
        ),
        # ADDED: finish_editing replaces the fragile DONE:/ERROR: plain-text protocol.
        # The enum constraint on `status` means Gemini's API validates the value before
        # the response reaches our code — the model physically cannot pass anything other
        # than "done" or "error". With plain-text parsing, startswith("DONE:") breaks
        # whenever Gemini adds filler ("I've made all changes. DONE: ..."), which
        # triggers a protocol_error even though the task completed successfully.
        types.FunctionDeclaration(
            name="finish_editing",
            description=(
                "Signal that the editing session is complete. "
                "Always call this tool to end the session — never output plain text to signal completion."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "status": types.Schema(
                        type="STRING",
                        enum=["done", "error"],
                        description=(
                            "'done' if all edits completed successfully. "
                            "'error' if the instruction is unclear or impossible to execute."
                        ),
                    ),
                    "summary": types.Schema(
                        type="STRING",
                        description=(
                            "Brief summary of what was changed (if done), "
                            "or why editing could not proceed (if error)."
                        ),
                    ),
                },
                required=["status", "summary"],
            ),
        ),
    ]
)


# ????????Check this with the Team ???????
# Maximum turns (each turn = one API call). Prevents infinite loops.
MAX_AGENT_TURNS = 20


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
    """Build the initial user message with the instruction and numbered file content."""
    numbered_lines = []
    for i, line in enumerate(file_content.split("\n"), start=1):
        numbered_lines.append(f"{i}: {line}")
    numbered = "\n".join(numbered_lines)
    return f"Instruction: {instruction}\n\nFile content:\n```\n{numbered}\n```"


def _build_file_state_message(file_content: str) -> str:
    """Build a file state update message after an edit."""
    numbered_lines = []
    for i, line in enumerate(file_content.split("\n"), start=1):
        numbered_lines.append(f"{i}: {line}")
    numbered = "\n".join(numbered_lines)
    return f"Updated file state:\n```\n{numbered}\n```"


# Agent loop
async def run_agent(
    instruction: str,
    content: str,
    *, # forces everything after to be keyword-only args
    model: str = "gemini-2.5-flash",
    report: bool = True,
    max_retries: int = 3,
) -> EditResult:
    """Run the agent loop to edit a file based on an instruction.

    Creates a Gemini client, sends the instruction + file content to the model,
    and loops: the model calls tools (regex_search, replace_line, etc.),
    we execute them on the FileEditor, send back results with updated file state,
    and repeat until the model responds with text (DONE/ERROR) or we hit limits.

    Args:
        instruction: Natural-language description of the desired edits.
        content: The plain-text file content to edit.
        model: The Gemini model to use.
        report: Whether to generate a structured change report.
        max_retries: Max consecutive tool errors before giving up.

    Returns:
        An EditResult with the edited content and optionally a change report.
    """
    client = _create_client() # gemini API connection
    editor = FileEditor(content) # holds the file as a mutable list of lines
    change_report = ChangeReport() if report else None # either a ChangeReport or None

    # Conversation history —> list of Content objects
    # Every message (user&Gemini) gets appended here, and this is sent on every API call
    contents: list[types.Content] = []

    # Initial user message with instruction + numbered file
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=_build_user_message(instruction, editor.content))],
        )
    )
    # DOCS about this setup
    # https://googleapis.github.io/python-genai/#generate-content 
    config = types.GenerateContentConfig( # Also passed on every API call
        system_instruction=SYSTEM_PROMPT,
        # This passes the schema tools to Gemini so it understands what's available
        tools=[TOOL_DECLARATIONS], # tool menu
        temperature=0.0,  # fully deterministic for editing tasks
    )

    consecutive_errors = 0  # consecutive tool errors, reset on success
    agent_status = "incomplete"  # updated when finish_editing is called

    # _turn means it needs a loop variable but doesn't use it
    # Loop runs at most 20 times (one API call per iter)
    for _turn in range(MAX_AGENT_TURNS):
        # The actual async call to Gemini
        # With function calling, can pass tools with generate_content()
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        # ADDED: Guard against empty candidates — the API can return an empty list
        # in rare cases (e.g. safety filters). Without this, candidates[0] crashes.
        if not response.candidates:
            break

        candidate = response.candidates[0] # returns response candidates, take the first

        # If the model responded with plain text (no tool calls), something unexpected happened.
        # The system prompt instructs Gemini to always call finish_editing instead of outputting text.
        if not _has_function_calls(candidate):
            break

        # FIXED: Only execute the FIRST function call per turn.
        # The original loop processed ALL function calls in one response, which is unsafe:
        # if Gemini returns two edits at once, the second one uses line numbers from before
        # the first edit ran — the file has shifted and it hits the wrong line.
        # Taking only the first fc and looping back forces one edit per API call,
        # so the model always sees the updated file state before its next move.
        fc = next(
            (part.function_call for part in candidate.content.parts if part.function_call is not None),
            None,
        )
        if fc is None:
            break

        args = dict(fc.args)

        # finish_editing signals the end of the session — extract status and stop
        if fc.name == "finish_editing":
            agent_status = args.get("status", "done")
            break

        # Append only the one function call we're executing to history
        contents.append(
            types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name=fc.name, args=args))],
            )
        )

        # Route it to the tool handler
        result = _dispatch_tool(editor, fc.name, args, change_report)

        # If tool call failed, increment error counter
        if result["status"] == "error":
            consecutive_errors += 1
            if consecutive_errors > max_retries:
                # Too many consecutive errors — return what we have
                return EditResult(
                    content=editor.content, report=change_report, status="incomplete"
                )
        else:
            consecutive_errors = 0

        # Include updated file state so the model sees current line numbers after edits.
        # Skipped for regex_search — the file didn't change, no need to re-send it.
        if fc.name != "regex_search":
            result["current_file_state"] = _build_file_state_message(editor.content)

        # Add the function response as a user message into convo history
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        # check docs https://googleapis.github.io/python-genai/genai.html#genai.types.FunctionResponse
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response=result,
                        )
                    )
                ],
            )
        )

    return EditResult(content=editor.content, report=change_report, status=agent_status)


# Tool dispatch


def _has_function_calls(candidate: types.Candidate) -> bool:
    """Check if a candidate response contains function calls."""
    if not candidate.content or not candidate.content.parts:
        return False
    return any(p.function_call is not None for p in candidate.content.parts)


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
        elif name == "replace_line":
            return _handle_replace(editor, args, change_report)
        elif name == "delete_line":
            return _handle_delete(editor, args, change_report)
        elif name == "add_line":
            return _handle_add(editor, args, change_report)
        elif name == "finish_editing":
            # finish_editing is handled before _dispatch_tool is called.
            # If it reaches here something went wrong in the routing logic.
            return {"status": "error", "message": "finish_editing should not be dispatched here"}
        else:
            return {"status": "error", "message": f"Unknown tool: {name}"}
    except (LineNumberError, ContentMismatchError) as e:
        return {"status": "error", "message": str(e)}
    except re.error as e:
        return {"status": "error", "message": f"Invalid regex pattern: {e}"}


def _handle_regex_search(editor: FileEditor, args: dict) -> dict:
    """Execute a regex search and return matches."""
    matches = editor.regex_search(args["pattern"])
    if not matches:
        return {"status": "success", "matches": [], "message": "No matches found."}
    return {
        "status": "success",
        "matches": [
            {
                "line_number": m.line_number,
                "line_content": m.line_content,
                "match_text": m.match_text,
            }
            for m in matches
        ],
    }


def _handle_replace(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line replacement and record the change."""
    line_number = int(args["line_number"])
    new_content = args["new_content"]
    expected_content = args.get("expected_content")

    before, after = editor.replace(line_number, new_content, expected_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[line_number],
                operation=OperationType.REPLACE,
                before=before,
                after=after,
                reason=args.get("reason", ""),
            )
        )

    return {"status": "success", "before": before, "after": after}


def _handle_delete(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line deletion and record the change."""
    line_number = int(args["line_number"])
    expected_content = args.get("expected_content")

    before = editor.delete(line_number, expected_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[line_number],
                operation=OperationType.DELETE,
                before=before,
                after="",
                reason=args.get("reason", ""),
            )
        )

    return {"status": "success", "deleted": before}


def _handle_add(
    editor: FileEditor, args: dict, report: ChangeReport | None
) -> dict:
    """Execute a line addition and record the change."""
    after_line = int(args["after_line"])
    new_content = args["new_content"]

    editor.add(after_line, new_content)

    if report is not None:
        report.add_change(
            ChangeEntry(
                line_numbers=[after_line + 1],
                operation=OperationType.ADD,
                before="",
                after=new_content,
                reason=args.get("reason", ""),
            )
        )

    return {"status": "success", "added": new_content, "at_line": after_line + 1}
