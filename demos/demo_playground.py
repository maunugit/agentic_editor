"""Interactive playground for trying the agentic editor with real content.

Supports two modes:
- simple: show the final edited content, status, and change report
- trace: show each turn, tool call, and tool result while the agent runs

Usage examples:
    source .venv/bin/activate
    python demos/demo_playground.py --mode simple --example markdown_cleanup
    python demos/demo_playground.py --mode trace --example json_fix
    python demos/demo_playground.py --mode simple --instruction "Replace 'teh' with 'the'." --content "teh cat"
    python demos/demo_playground.py --mode trace --instruction-file instruction.txt --content-file sample.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentic_editor import EditResult
from agentic_editor.agent import run_agent


EXAMPLES = {
    "plain_replace": {
        "description": "Small plain-text correction.",
        "instruction": 'Replace "teh" with "the" in the sentence.',
        "content": "The quick brown fox jumps over teh lazy dog.",
    },
    "markdown_cleanup": {
        "description": "Markdown typo fix plus TODO deletion.",
        "instruction": (
            '1. The heading has "Pyhton" - fix it to "Python"\n'
            '2. Remove the line that says "TODO: REMOVE THIS LINE BEFORE PUBLISHING"'
        ),
        "content": (
            "# Introduction to Pyhton\n\n"
            "Python is a popular programming language.\n"
            "TODO: REMOVE THIS LINE BEFORE PUBLISHING\n\n"
            "## Features\n\n"
            "- Easy to learn\n"
            "- Versatile\n"
        ),
    },
    "json_fix": {
        "description": "JSON value correction and typo repair.",
        "instruction": (
            '1. The value of "planet_count" is wrong - change it from 7 to 8\n'
            '2. Change "Genetcs" to "Genetics" in the second module title'
        ),
        "content": (
            '{\n'
            '  "title": "The Solar System",\n'
            '  "planet_count": 7,\n'
            '  "modules": [\n'
            '    {"id": 1, "title": "Cells"},\n'
            '    {"id": 2, "title": "Genetcs"}\n'
            '  ]\n'
            '}'
        ),
    },
    "html_fix": {
        "description": "HTML content correction with multiple explicit fixes.",
        "instruction": (
            '1. "Solar Sytem" in the h1 tag is a typo - fix it to "Solar System"\n'
            '2. Replace "7 planets" with "8 planets"\n'
            '3. Replace "Saturn" with "Jupiter" in the sentence about the largest planet'
        ),
        "content": (
            "<html>\n"
            "<body>\n"
            "  <h1>The Solar Sytem</h1>\n"
            "  <p>There are 7 planets in our solar system.</p>\n"
            "  <p>The largest planet is Saturn.</p>\n"
            "</body>\n"
            "</html>"
        ),
    },
    "json_ambiguous": {
        "description": "Ambiguous JSON example that should require local context.",
        "instruction": (
            'In the module where "id": 102, change the title from '
            '"Introduction" to "Deep Dive". Do not change the other title lines.'
        ),
        "content": (
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
        ),
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("simple", "trace"),
        default="simple",
        help="Whether to print only the final result or the step-by-step trace.",
    )
    parser.add_argument(
        "--example",
        choices=sorted(EXAMPLES.keys()),
        help="Run one of the built-in demo scenarios.",
    )
    parser.add_argument("--instruction", help="Instruction text to run.")
    parser.add_argument("--instruction-file", help="Path to a file containing the instruction.")
    parser.add_argument("--content", help="Inline content string to edit.")
    parser.add_argument("--content-file", help="Path to a file containing content to edit.")
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model to use. Defaults to gemini-2.5-flash.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Disable structured change-report generation.",
    )
    return parser


def load_text_arg(inline_text: str | None, file_path: str | None) -> str | None:
    if inline_text:
        return inline_text
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return None


def resolve_inputs(args: argparse.Namespace) -> tuple[str, str, str | None]:
    if args.example:
        example = EXAMPLES[args.example]
        return example["instruction"], example["content"], example["description"]

    instruction = load_text_arg(args.instruction, args.instruction_file)
    content = load_text_arg(args.content, args.content_file)

    if instruction is None:
        print("Enter instruction, then press Ctrl-D when finished:\n", file=sys.stderr)
        instruction = sys.stdin.read().strip()

    if content is None:
        raise SystemExit(
            "Provide --content, --content-file, or --example. "
            "Interactive content input is not supported in the same stdin stream as instruction."
        )

    if not instruction or not instruction.strip():
        raise SystemExit("Instruction must not be empty.")
    if content == "":
        raise SystemExit("Content must not be empty.")

    return instruction, content, None


def print_section(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(title)
    print(f"{'=' * 72}")


def print_text_block(text: str) -> None:
    print(text.rstrip())


def print_result(result: EditResult, original_content: str) -> None:
    print_section("Original Content")
    print_text_block(original_content)

    print_section("Edited Content")
    print_text_block(result.content)

    print_section("Result Metadata")
    print(f"status: {result.status}")
    print(f"completed: {result.completed}")
    print(f"final_message: {result.final_message}")

    print_section("Change Report")
    if result.report is None:
        print("report disabled")
    else:
        print(json.dumps(result.report.to_dict(), indent=2, ensure_ascii=False))


def make_trace_callback() -> callable:
    def _callback(event: dict) -> None:
        event_type = event["type"]

        if event_type == "run_started":
            print_section("Run Started")
            print(f"model: {event['model']}")
            print(f"report_enabled: {event['report_enabled']}")
            print(f"file_metadata: {json.dumps(event['file_metadata'], indent=2)}")
            return

        if event_type == "turn_started":
            print_section(f"Turn {event['turn']}")
            return

        if event_type == "model_function_call":
            print(f"Function call: {event['name']}")
            print(json.dumps(event["args"], indent=2, ensure_ascii=False))
            return

        if event_type == "tool_result":
            print(f"Tool result for {event['name']}:")
            print(json.dumps(event["result"], indent=2, ensure_ascii=False))
            return

        if event_type == "model_text_response":
            print("Model text response:")
            print(event["text"])
            return

        if event_type == "run_finished":
            print_section("Run Finished")
            print(f"status: {event['status']}")
            print(f"completed: {event['completed']}")
            print(f"final_message: {event['final_message']}")
            return

    return _callback


async def main_async(args: argparse.Namespace) -> None:
    load_dotenv()
    instruction, content, description = resolve_inputs(args)

    if description:
        print_section("Example")
        print(description)

    print_section("Instruction")
    print_text_block(instruction)

    trace_callback = make_trace_callback() if args.mode == "trace" else None
    result = await run_agent(
        instruction=instruction,
        content=content,
        model=args.model,
        report=not args.no_report,
        trace_callback=trace_callback,
    )
    print_result(result, content)


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        raise SystemExit("\nInterrupted.")


if __name__ == "__main__":
    main()
