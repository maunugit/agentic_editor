"""Compatibility wrapper for the demo playground trace mode.

Usage:
    source .venv/bin/activate
    python demos/demo_agent_loop.py
"""

from __future__ import annotations

import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from demo_playground import main_async, build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(["--mode", "trace", "--example", "markdown_cleanup"])
    import asyncio

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
