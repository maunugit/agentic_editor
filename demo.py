"""Interactive demo for agentic-editor.

Run with:  python demo.py
Type "quit" at any prompt to exit.
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from agentic_editor import edit_file

_LAST_FILE = os.path.join(os.path.dirname(__file__), ".last_file")


def _remember_path(path: str) -> None:
    with open(_LAST_FILE, "w", encoding="utf-8") as f:
        f.write(path)


def _recall_path() -> str | None:
    try:
        with open(_LAST_FILE, "r", encoding="utf-8") as f:
            p = f.read().strip()
            return p if p else None
    except FileNotFoundError:
        return None


# ── Quit-aware input ──────────────────────────────────────────────────────────

class _Quit(Exception):
    pass

def _input(prompt: str = "") -> str:
    """input() that raises _Quit if the user types quit/q/exit."""
    val = input(prompt).strip()
    if val.lower() in ("quit", "q", "exit"):
        raise _Quit
    return val


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_binary(filepath: str) -> bool:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return "\x00" in content
    except (UnicodeDecodeError, ValueError):
        return True


def _show_file(content: str, label: str = "CURRENT FILE") -> None:
    print(f"\n── {label} {'─' * (54 - len(label))}")
    for i, line in enumerate(content.split("\n"), 1):
        print(f"  {i:3}: {line}")
    print("─" * 60)


def _show_report(report) -> None:
    print(f"\n── CHANGE REPORT {'─' * 43}")
    if not report or not report.changes:
        print("  no changes recorded")
        print("─" * 60)
        return
    for i, c in enumerate(report.changes, 1):
        print(f"\n  Change {i}:")
        print(f"    operation : {c.operation.value}")
        print(f"    line(s)   : {c.line_numbers}")
        print(f"    before    : {c.before!r}")
        print(f"    after     : {c.after!r}")
        print(f"    reason    : {c.reason}")
    print("─" * 60)


def _save_prompt(content: str, original_path: str | None) -> None:
    if original_path:
        # Already know the path — just ask yes/no/new
        print(f"\nSave?  [y] overwrite {original_path}   [n] skip   [p] different path")
        try:
            choice = _input("\n> ").lower()
        except _Quit:
            raise
        if choice == "y":
            with open(original_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  ✓ Saved to {original_path}")
        elif choice == "p":
            try:
                path = _input("  New file path: ").strip('"').strip("'")
            except _Quit:
                raise
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  ✓ Saved to {path}")
    else:
        # Pasted content — offer last used path as default if available
        last = _recall_path()
        if last:
            print(f"\nSave?  [y] save to {last}   [n] skip   [p] different path")
        else:
            print("\nSave?  [y] save to a file   [n] skip")
        try:
            choice = _input("\n> ").lower()
        except _Quit:
            raise
        if choice == "y":
            save_path = last if last else None
            if not save_path:
                try:
                    save_path = _input("  File path: ").strip('"').strip("'")
                except _Quit:
                    raise
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            _remember_path(save_path)
            print(f"  ✓ Saved to {save_path}")
        elif choice == "p":
            try:
                save_path = _input("  File path: ").strip('"').strip("'")
            except _Quit:
                raise
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            _remember_path(save_path)
            print(f"  ✓ Saved to {save_path}")


# ── Input loading ─────────────────────────────────────────────────────────────

def _load_input() -> tuple[str | None, str | None]:
    print("\nWhat do you want to edit?")
    print("  1. Paste text directly")
    print("  2. Load from a file path")

    try:
        choice = _input("\n> ")
    except _Quit:
        raise

    if choice == "1":
        print('\nPaste your content. Type "END" on a new line when done:\n')
        lines = []
        while True:
            line = input()          # raw input — END is the terminator, not quit
            if line.strip() == "END":
                break
            lines.append(line)
        content = "\n".join(lines)
        if not content.strip():
            print("  ✗ No content entered.")
            return None, None
        return content, None

    elif choice == "2":
        last = _recall_path()
        if last:
            print(f"\n  Last used: {last}")
            print("  Press Enter to use it, or type a new path.")
        try:
            raw = _input("\nFile path: ").strip('"').strip("'")
        except _Quit:
            raise
        path = raw if raw else (last or "")
        if not path:
            return None, None
        try:
            if _is_binary(path):
                print("\n  ✗ Binary file detected — only plain-text formats are supported.")
                print("    (JSON, HTML, Markdown, Python code, .txt, etc.)")
                return None, None
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            line_count = content.count("\n") + 1
            print(f"\n  ✓ Loaded {line_count} lines from {path}")
            _remember_path(path)
            return content, path
        except FileNotFoundError:
            print(f"\n  ✗ File not found: {path}")
            return None, None

    else:
        print("  Invalid choice.")
        return None, None


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n" + "═" * 60)
    print("  Agentic Editor — Interactive Demo")
    print("═" * 60)
    print('  Type "quit" at any prompt to exit.')
    print('  Type "reset" at the instruction prompt to load a new file.')
    print("═" * 60)

    current_content: str | None = None
    current_path: str | None = None

    try:
        while True:
            # ── Load a file if we don't have one ─────────────────────────
            while current_content is None:
                current_content, current_path = _load_input()

            # ── Show current file state ───────────────────────────────────
            _show_file(current_content)

            # ── Get instruction ───────────────────────────────────────────
            print('\nInstruction  (or "reset" to load a new file):')
            instruction = _input("\n> ")

            if not instruction:
                continue

            if instruction.lower() in ("reset", "r"):
                current_content = None
                current_path = None
                continue

            # ── Run the agent ─────────────────────────────────────────────
            print("\n  Running...\n")
            try:
                result = await edit_file(instruction=instruction, content=current_content)
            except Exception as e:
                print(f"\n  ✗ Error: {e}")
                continue

            # ── Show results ──────────────────────────────────────────────
            _show_file(result.content, label="EDITED FILE")
            _show_report(result.report)

            # ── Save prompt ───────────────────────────────────────────────
            _save_prompt(result.content, current_path)

            # ── Update state ──────────────────────────────────────────────
            current_content = result.content

            # ── What next ────────────────────────────────────────────────
            print("\nWhat next?  [e] another instruction   [r] new file   [q] quit")
            nxt = _input("\n> ").lower()

            if nxt in ("r", "reset"):
                current_content = None
                current_path = None
            # else [e] or anything else → loop back with updated content

    except _Quit:
        print("\n  Bye!\n")


if __name__ == "__main__":
    asyncio.run(main())
