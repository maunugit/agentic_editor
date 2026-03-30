"""Agentic Editor — LLM-driven line-by-line text editing via regex tools.

Usage:
    from agentic_editor import edit_file, EditResult, ChangeReport

    result = await edit_file(
        instruction="Fix the JSON syntax errors",
        content="{ invalid json }",
    )
    print(result.content)       # edited file content
    print(result.report)        # structured change report (or None)
"""

from agentic_editor.models import (
    ChangeEntry,
    ChangeReport,
    EditResult,
    OperationType,
)

__all__ = [
    "edit_file",
    "ChangeEntry",
    "ChangeReport",
    "EditResult",
    "OperationType",
]


async def edit_file(
    instruction: str,
    content: str,
    *,
    model: str = "gemini-2.5-flash",
    report: bool = True,
    max_retries: int = 3,
) -> EditResult:
    """Edit a plain-text file according to a natural-language instruction.

    This is the main entry point for the agentic editor. It spins up an LLM
    agent that uses regex tools to locate lines and performs deterministic
    line-level edits (replace, delete, add).

    Args:
        instruction: Natural-language description of the desired edits.
        content: The plain-text file content to edit.
        model: The Gemini model to use. Defaults to "gemini-2.5-flash".
        report: Whether to generate a structured change report. Defaults to True.
        max_retries: Max retry attempts for failed tool calls. Defaults to 3.

    Returns:
        An EditResult containing the edited content and optionally a change report.

    Raises:
        ValueError: If instruction or content is empty.
    """
    if not instruction or not instruction.strip():
        raise ValueError("instruction must not be empty")
    if not content:
        raise ValueError("content must not be empty")

    from agentic_editor.agent import run_agent

    return await run_agent(
        instruction=instruction,
        content=content,
        model=model,
        report=report,
        max_retries=max_retries,
    )
