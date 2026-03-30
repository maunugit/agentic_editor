# AGENTS.md

## Purpose

`agentic-editor` is a standalone async Python package that performs surgical edits on plain-text files using an LLM-guided tool loop.

The intended usage is:
- an upstream system identifies a specific issue in generated content
- it sends this package a clear natural-language repair instruction
- Gemini locates the target through tools
- Python executes the edit deterministically
- the package returns edited content plus a structured change report

This project is not primarily meant to read a whole file and broadly decide what is wrong. It is meant to carry out targeted repairs described explicitly by the caller.


## Session Startup

At the start of a fresh development session:

- inspect `AGENTS.md`, `ROADMAP.md`, `README.md`, and the most relevant code files
- form a concise understanding of the current architecture, current phase, and open priorities
- summarize the repo state before making changes
- treat `docs_archive/` as historical reference material, not canonical documentation


## Current Architecture

The current prototype uses a retrieval-first agent loop.

Important properties:

- file content stays in Python memory during a request
- Gemini does not receive the full file by default
- the initial prompt contains only:
  - the instruction
  - a note that the full file is not in context
  - compact file metadata such as total line count and approximate character count
- Gemini must inspect the file through tools before editing it

Current tool set:

- `regex_search(pattern)`:
  search the file for candidate lines using Python regex
- `get_line(line_number)`:
  read one exact line
- `get_lines(start_line, end_line)`:
  read a small bounded range of lines
- `replace_line(line_number, new_content, expected_content, reason?)`
- `delete_line(line_number, expected_content, reason?)`
- `add_line(after_line, new_content, reason?)`

The LLM never executes Python functions directly. It only requests tool calls through Gemini `FunctionDeclaration` schemas. Python owns execution, validation, retries, and reporting.


## Agent Loop

`run_agent()` in `src/agentic_editor/agent.py` currently works like this:

1. Create the Gemini client using `GEMINI_API_KEY`.
2. Create a `FileEditor` with the full file content held in memory.
3. Create a `ChangeReport` unless `report=False`.
4. Build the initial user message from:
   - the repair instruction
   - compact file metadata only
5. Call Gemini with:
   - the system prompt
   - the `FunctionDeclaration` tool schemas
   - the accumulated conversation history
6. Inspect the response:
   - if Gemini returns tool calls, dispatch them through Python
   - if Gemini returns text, only accept it as terminal if it starts with `DONE:` or `ERROR:`
7. If Gemini returns one or more tool calls in a response:
   - execute only the first tool call
   - catch and return retryable errors
   - record actual changes in `ChangeReport`
   - append only that executed tool call and its structured `FunctionResponse` back into the conversation
   - then call Gemini again so the next step is planned against the updated file state
8. Stop when:
   - Gemini returns `DONE:`
   - Gemini returns `ERROR:`
   - the run hits the max consecutive tool-error limit
   - the run hits the max turn limit
   - Gemini returns an invalid plain-text protocol response
9. Return an `EditResult`.


## Safety And Determinism

These behaviors are intentional and should be preserved:

- regex is a search tool only
- edit operations are deterministic Python operations
- `replace_line` and `delete_line` require `expected_content` verification
- `before` and `after` values are captured from actual file state, not model output
- line numbers are always interpreted against the current file state
- the model must retrieve local context explicitly instead of receiving the whole file
- invalid plain-text terminal responses are treated as protocol errors
- incomplete runs return explicit terminal metadata
- partial/incomplete runs keep the changes that were actually executed as a partial audit trail


## Data Models

Defined in `src/agentic_editor/models.py`:

- `ChangeEntry`:
  one executed edit, with `line_numbers`, `operation`, `before`, `after`, and `reason`
- `ChangeReport`:
  collection of `ChangeEntry` records
- `EditResult`:
  final return object with:
  - `content`
  - `report`
  - `status`
  - `final_message`
  - `completed`

Current `reason` behavior:

- `reason` is a short audit-label explanation
- the model may provide a short edit-level reason
- if not, Python uses a deterministic fallback label


## File Responsibilities

Current core files:

- `src/agentic_editor/__init__.py`
  public API entrypoint via `edit_file(...)`
- `src/agentic_editor/agent.py`
  Gemini client setup, system prompt, tool schemas, agent loop, dispatch, terminal-state handling, optional trace callback
- `src/agentic_editor/tools.py`
  `FileEditor`, bounded read tools, regex search, replace/delete/add operations, validation errors
- `src/agentic_editor/models.py`
  `ChangeEntry`, `ChangeReport`, `EditResult`, `OperationType`


## Current Repo Layout

```text
agentic_editor/
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── pyproject.toml
├── demos/
│   ├── demo_playground.py
│   └── demo_agent_loop.py
├── docs_archive/
│   └── ... historical notes and earlier design docs
├── src/
│   └── agentic_editor/
│       ├── __init__.py
│       ├── agent.py
│       ├── tools.py
│       └── models.py
└── tests/
    ├── conftest.py
    ├── test_tools.py
    ├── test_models.py
    ├── test_api.py
    ├── test_agent.py
    └── test_integration.py
```

`docs_archive/` contains older planning notes, redesign notes, and historical walkthroughs. Those files may be useful for reference, but they should not be treated as the active source of truth unless explicitly requested.


## Testing

Current test layers:

- `tests/test_tools.py`
  deterministic `FileEditor` behavior
- `tests/test_models.py`
  data model behavior
- `tests/test_api.py`
  public API contract with mocked agent entrypoint
- `tests/test_agent.py`
  focused agent-loop/helper behavior
- `tests/test_integration.py`
  live Gemini end-to-end scenarios

Live integration tests are opt-in and require both:

- `GEMINI_API_KEY`
- `RUN_GEMINI_INTEGRATION_TESTS=1`

Useful commands:

- unit/helper tests:
  `.venv/bin/python -m pytest tests/test_tools.py tests/test_models.py tests/test_api.py tests/test_agent.py -v`
- live integration tests:
  `RUN_GEMINI_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/test_integration.py -v`
- full local suite without live integration:
  `.venv/bin/python -m pytest tests/test_tools.py tests/test_models.py tests/test_api.py tests/test_agent.py -v`


## Demo Playground

The repo includes a demo playground for manual exploration:

- `demos/demo_playground.py`

Supported modes:

- `simple`
  show final content, result metadata, and change report
- `trace`
  show the step-by-step tool loop through the optional trace callback

Examples:

- `python demos/demo_playground.py --mode simple --example markdown_cleanup`
- `python demos/demo_playground.py --mode trace --example json_fix`
- `python demos/demo_playground.py --mode simple --instruction "Replace 'teh' with 'the'." --content "teh cat"`

`demos/demo_agent_loop.py` is now a compatibility wrapper that launches the trace demo.


## Current Development Guidance

- prefer `AGENTS.md` and `ROADMAP.md` over archived notes
- keep the retrieval-first design intact unless deliberately redesigning it
- do not reintroduce full-file prompt injection without explicit reason
- preserve deterministic edit execution and content verification
- keep incomplete-run behavior explicit rather than silent
- when unsure about current scope, treat evaluator-style explicit repair instructions as the default product mode
