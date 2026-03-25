"""Demo script that shows the agent's reasoning process in the terminal.

Calls the real Gemini API with a realistic Thinglink-style scenario:
an evaluator agent has found errors in a generated learning block and
sends specific fix instructions to our editing tool.

Usage:
    source .venv/bin/activate
    python demos/demo_agent_loop.py

Requires GEMINI_API_KEY in .env or environment.
"""

import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv

# Add src to path so we can import agentic_editor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from google.genai import types

from agentic_editor.agent import (
    SYSTEM_PROMPT,
    TOOL_DECLARATIONS,
    MAX_AGENT_TURNS,
    _create_client,
    _build_user_message,
    _build_file_state_message,
    _dispatch_tool,
    _has_function_calls,
)
from agentic_editor.models import ChangeReport, EditResult
from agentic_editor.tools import FileEditor


# ── Terminal colors ─────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


# ── Demo scenario ──────────────────────────────────────────────────────────

SAMPLE_FILE = """\
# The Solar System: An Introduction

The Solar System consists of the Sun and the objects that orbit it.

## The Sun

The Sun is a star at the center of our Solar System. It is approximately 93 billion miles from Earth.
The Sun accounts for about 99.86% of the total mass of the Solar Sytem.

## Inner Planets

The four inner planets are Mercury, Venus, Earth, and Mars. These are also known as the terrestial planets.

They are relatively small and composed mostly of rock and metal.
They are relatively small and composed mostly of rock and metal.

## Outer Planets

The four outer planets are Jupiter, Saturn, Uranus, and Neptune. These are also known as gas giants, although Uranus and Neptune are more specifically ice giants.

Jupiter is the largest planet in our Solar System, with a mass of about 318 times that of Earth."""

INSTRUCTION = """\
The following issues were detected in this learning block by QA agent:
1. Line with "93 billion miles" —> factual error, should be "93 million miles"
2. "Solar Sytem" is a typo —> fix to "Solar System"
3. "terrestial" is a typo —> fix to "terrestrial"
4. There is a duplicate line "They are relatively small and composed mostly of rock and metal.", remove the second occurrence"""


# ── Logging helpers ─────────────────────────────────────────────────────────

def print_header(text: str) -> None:
    width = 70
    print(f"\n{BOLD}{CYAN}{'═' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * width}{RESET}\n")


def print_turn(turn: int) -> None:
    print(f"\n{BOLD}{'─' * 50}{RESET}")
    print(f"{BOLD}  Turn {turn}{RESET}")
    print(f"{BOLD}{'─' * 50}{RESET}")


def print_tool_call(name: str, args: dict) -> None:
    icons = {
        "regex_search": f"{YELLOW}SEARCH{RESET}",
        "replace_line": f"{GREEN}REPLACE{RESET}",
        "delete_line": f"{RED}DELETE{RESET}",
        "add_line": f"{BLUE}ADD{RESET}",
    }
    icon = icons.get(name, name)
    print(f"\n  {icon}  {BOLD}{name}{RESET}")

    for key, value in args.items():
        if key == "expected_content":
            print(f"    {DIM}expected:{RESET} {repr(value)}")
        elif key == "new_content":
            print(f"    {GREEN}new:{RESET}      {repr(value)}")
        elif key == "pattern":
            print(f"    {YELLOW}pattern:{RESET}  {repr(value)}")
        elif key == "line_number":
            print(f"    {DIM}line:{RESET}     {value}")
        elif key == "after_line":
            print(f"    {DIM}after:{RESET}    line {value}")


def print_tool_result(result: dict) -> None:
    status = result["status"]
    if status == "error":
        print(f"    {RED}✗ Error: {result['message']}{RESET}")
        return

    if "matches" in result:
        matches = result["matches"]
        if not matches:
            print(f"    {DIM}→ No matches found{RESET}")
        else:
            for m in matches:
                print(f"    {DIM}→ Line {m['line_number']}: {repr(m['line_content'])}{RESET}")
    elif "before" in result and "after" in result:
        print(f"    {DIM}→ Before: {repr(result['before'])}{RESET}")
        print(f"    {GREEN}→ After:  {repr(result['after'])}{RESET}")
    elif "deleted" in result:
        print(f"    {DIM}→ Deleted: {repr(result['deleted'])}{RESET}")
    elif "added" in result:
        print(f"    {GREEN}→ Added at line {result['at_line']}: {repr(result['added'])}{RESET}")


def print_agent_text(text: str) -> None:
    print(f"\n  {MAGENTA}Agent says:{RESET} {text}")


def print_file_state(content: str, label: str) -> None:
    print(f"\n{DIM}  ┌─ {label} ─────────────────────────────────{RESET}")
    for i, line in enumerate(content.split("\n"), start=1):
        print(f"{DIM}  │ {i:>2}: {line}{RESET}")
    print(f"{DIM}  └{'─' * 48}{RESET}")


# ── The demo agent loop (with logging) ─────────────────────────────────────

async def run_demo() -> None:
    load_dotenv()

    print_header("AGENTIC EDITOR — DEMO")

    print(f"{BOLD}Scenario:{RESET} Thinglink's evaluator agent found issues in a generated")
    print(f"learning block and is sending fix instructions to our editing tool.\n")

    print(f"{BOLD}Instruction:{RESET}")
    for line in INSTRUCTION.strip().split("\n"):
        print(f"  {line}")

    print_file_state(SAMPLE_FILE, "ORIGINAL FILE")

    # Set up — same as run_agent() but with logging
    client = _create_client()
    editor = FileEditor(SAMPLE_FILE)
    change_report = ChangeReport()

    contents: list[types.Content] = []
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=_build_user_message(INSTRUCTION, editor.content))],
        )
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[TOOL_DECLARATIONS],
        temperature=0.0,
    )

    print_header("AGENT LOOP STARTS")

    consecutive_errors = 0
    total_api_time = 0.0

    for turn in range(1, MAX_AGENT_TURNS + 1):
        print_turn(turn)

        start = time.time()
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )
        elapsed = time.time() - start
        total_api_time += elapsed
        print(f"  {DIM}API response in {elapsed:.1f}s{RESET}")

        candidate = response.candidates[0]

        # Check for text-only response (agent is done)
        if not _has_function_calls(candidate):
            text_parts = [
                p.text for p in candidate.content.parts
                if p.text
            ]
            if text_parts:
                print_agent_text(" ".join(text_parts))
            break

        # Process function calls
        contents.append(candidate.content)
        function_response_parts: list[types.Part] = []

        for part in candidate.content.parts:
            if part.function_call is None:
                continue

            fc = part.function_call
            args = dict(fc.args)

            print_tool_call(fc.name, args)

            result = _dispatch_tool(editor, fc.name, args, change_report)

            print_tool_result(result)

            if result["status"] == "error":
                consecutive_errors += 1
                if consecutive_errors > 3:
                    print(f"\n  {RED}✗ Too many consecutive errors — stopping{RESET}")
                    break
            else:
                consecutive_errors = 0

            result["current_file_state"] = _build_file_state_message(editor.content)

            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response=result,
                    )
                )
            )

        contents.append(
            types.Content(role="user", parts=function_response_parts)
        )

    # ── Results ─────────────────────────────────────────────────────────────

    print_header("RESULTS")

    print_file_state(editor.content, "EDITED FILE")

    print(f"\n{BOLD}Change Report:{RESET}")
    report_dict = change_report.to_dict()
    print(json.dumps(report_dict, indent=2))

    print(f"\n{DIM}Total API time: {total_api_time:.1f}s across {turn} turn(s){RESET}")
    print(f"{DIM}Changes made: {len(change_report.changes)}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_demo())
