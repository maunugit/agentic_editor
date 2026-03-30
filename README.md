# Agentic Editor

A standalone async Python package that takes a natural-language instruction and a plain-text file, uses an LLM agent with regex tools to perform line-by-line edits (replace, delete, add), and returns the edited file along with a structured JSON change report.

Built by UEF for Thinglink's Scenario Builder pipeline.

## How It Works

The tool uses a Gemini LLM as the decision-maker and Python as the executor:

1. Python stores the full file content in memory for the duration of the request
2. Gemini receives the instruction plus compact file metadata, not the full file by default
3. Gemini uses retrieval tools such as `regex_search`, `get_line`, and `get_lines` to inspect local context
4. Gemini requests edit tools such as `replace_line`, `delete_line`, or `add_line`
5. Python executes each edit deterministically and records actual changes
6. The loop continues until Gemini returns `DONE:` or `ERROR:`, or the run hits an explicit safety cap
7. The edited file and structured result metadata are returned

The LLM never edits the file directly. It requests tool calls through Gemini `FunctionDeclaration` schemas, while Python owns file state, validation, retries, and change tracking.

## Usage

```python
from agentic_editor import edit_file

result = await edit_file(
    instruction='Fix "93 billion miles" to "93 million miles"',
    content="The Sun is approximately 93 billion miles from Earth.",
)

print(result.content)  # "The Sun is approximately 93 million miles from Earth."
print(result.report.to_dict())  # structured JSON change report
```

### Parameters

```python
await edit_file(
    instruction="...",          # natural-language editing instruction
    content="...",              # plain-text file content (JSON, HTML, Markdown, Python, etc.)
    model="gemini-2.5-flash",  # Gemini model to use (default: gemini-2.5-flash)
    report=True,                # generate change report (default: True)
    max_retries=3,              # max consecutive tool errors before stopping (default: 3)
)
```

### Return Value

`edit_file()` returns an `EditResult` with:
- `result.content` — the edited file as a string
- `result.report` — a `ChangeReport` object (or `None` if `report=False`)
- `result.status` — terminal status such as `done`, `error`, or an incomplete/protocol state
- `result.final_message` — final model or runtime message describing the terminal state
- `result.completed` — whether the run completed successfully

The change report contains a list of changes, each with `line_numbers`, `operation`, `before`, `after`, and `reason` fields. `before` and `after` are captured from real file state, not from LLM output.

## Installation

Requires Python 3.11+.

```bash
pip install git+<repository-url>
```

For development:

```bash
git clone <repository-url>
cd agentic_editor
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Set your Gemini API key as an environment variable:

```bash
export GEMINI_API_KEY="your-key-here"
```

Or in a `.env` file (for local development):

```
GEMINI_API_KEY=your-key-here
```

## Running Tests

```bash
# Unit/helper tests (no API key needed)
pytest tests/test_tools.py tests/test_models.py tests/test_api.py tests/test_agent.py -v

# Live integration tests (requires GEMINI_API_KEY and explicit opt-in)
RUN_GEMINI_INTEGRATION_TESTS=1 pytest tests/test_integration.py -v

# Full local non-live test suite
pytest tests/test_tools.py tests/test_models.py tests/test_api.py tests/test_agent.py -v

# All tests, including live integration when enabled
pytest -v
```

## Demo

A demo playground is included for manual exploration of the tool:

```bash
python demos/demo_playground.py --mode simple --example markdown_cleanup
python demos/demo_playground.py --mode trace --example json_fix
```

`demos/demo_agent_loop.py` remains available as a compatibility wrapper that launches the trace demo.

## Project Structure

```
agentic_editor/
├── README.md
├── pyproject.toml
├── demos/
│   ├── demo_playground.py   # manual playground with simple and trace modes
│   └── demo_agent_loop.py   # compatibility wrapper for trace demo
├── docs_archive/            # historical notes and earlier design docs
├── src/
│   └── agentic_editor/
│       ├── __init__.py      # public API (edit_file)
│       ├── agent.py         # retrieval-first agent loop, Gemini client, tool declarations
│       ├── tools.py         # FileEditor: bounded reads, regex search, replace, delete, add
│       └── models.py        # data models (ChangeEntry, ChangeReport, EditResult)
├── tests/
│   ├── conftest.py          # loads .env for tests
│   ├── test_tools.py        # FileEditor unit tests
│   ├── test_models.py       # data model unit tests
│   ├── test_api.py          # public API unit tests (mocked)
│   ├── test_agent.py        # focused agent-loop/helper tests
│   └── test_integration.py  # opt-in live Gemini API tests
```

## Progress

- **Phase 1 — Project Scaffolding & Core Data Models:** Complete
- **Phase 2 — Edit Operations & Regex Tool:** Complete
- **Phase 3 — Agent Loop & Gemini Integration:** Complete
- **Phase 4 — Change Report & Output:** In progress
- **Phase 5 — Documentation & Packaging:** Not started

## Tech Stack

- **Python** (async, 3.11+)
- **Gemini 2.5 Flash** via the `google-genai` SDK
- **pytest** + **pytest-asyncio** for testing
