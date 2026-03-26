# Agentic Editor

A standalone async Python package that takes a natural-language instruction and a plain-text file, uses an LLM agent with regex tools to perform line-by-line edits (replace, delete, add), and returns the edited file along with a structured JSON change report.

Built by UEF for Thinglink's Scenario Builder pipeline.

## How It Works

The tool uses a Gemini LLM as the decision-maker and Python as the executor:

1. The LLM receives an instruction and the file content with numbered lines
2. The LLM calls `regex_search` to locate target lines by pattern
3. The LLM decides the operation (`replace_line`, `delete_line`, or `add_line`)
4. Python executes the edit deterministically and records the change
5. The LLM receives the updated file state and repeats until done
6. The edited file and a structured change report are returned

The LLM never edits the file directly, it only decides what to do. Python performs the actual edits and captures the before/after from real file text.

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

The change report contains a list of changes, each with `line_numbers`, `operation`, `before`, `after`, and `reason` fields.

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
# Unit tests (no API key needed)
pytest tests/test_tools.py tests/test_models.py tests/test_api.py -v

# Integration tests (requires GEMINI_API_KEY)
pytest tests/test_integration.py -v

# All tests
pytest -v
```

## Demo

A demo script is included that shows the agent's reasoning process in the terminal with a realistic Thinglink scenario:

```bash
python demos/demo_agent_loop.py
```

## Project Structure

```
agentic_editor/
├── README.md
├── pyproject.toml
├── src/
│   └── agentic_editor/
│       ├── __init__.py      # public API (edit_file)
│       ├── agent.py         # agent loop, Gemini client, tool declarations
│       ├── tools.py         # FileEditor: regex search, replace, delete, add
│       └── models.py        # data models (ChangeEntry, ChangeReport, EditResult)
├── tests/
│   ├── conftest.py          # loads .env for tests
│   ├── test_tools.py        # FileEditor unit tests
│   ├── test_models.py       # data model unit tests
│   ├── test_api.py          # public API unit tests (mocked)
│   └── test_integration.py  # live Gemini API tests
└── demos/
    └── demo_agent_loop.py   # terminal demo with logging
```

## Progress

- **Phase 1 — Project Scaffolding & Core Data Models:** Complete
- **Phase 2 — Edit Operations & Regex Tool:** Complete
- **Phase 3 — Agent Loop & Gemini Integration:** Complete
- **Phase 4 — Change Report Refinement & End-to-End Tests:** In progress
- **Phase 5 — Documentation & Packaging:** Not started

## Tech Stack

- **Python** (async, 3.11+)
- **Gemini 2.5 Flash** via the `google-genai` SDK
- **pytest** + **pytest-asyncio** for testing
