# Phase 3: Agent Loop & Gemini Integration

## Context

Phases 1-2 are complete — models and tools are solid. The `agent.py` file is a placeholder and `edit_file()` returns content unchanged. Phase 3 wires in the Gemini API to make the agent actually work: receive an instruction, use regex tools to find lines, perform edits, return results.

Implementation is done in incremental steps so each can be verified independently.

## SDK Decision

Use `client.aio.models.generate_content()` with `FunctionDeclaration` tools — **not** the `interactions` API (private/experimental `_interactions` module). Using declarations (not callables) disables Gemini's Automatic Function Calling, giving us full control over the loop.

## Step 1: Client setup, system prompt, tool declarations

**File: `src/agentic_editor/agent.py`** (rewrite)

- `_create_client()` — reads `GEMINI_API_KEY` from env, creates `genai.Client(api_key=...)`
- `SYSTEM_PROMPT` — tailored for literal instructions: locate via regex, execute edit, be concise, always search before editing, always provide `expected_content`, respond with "DONE:" when finished
- `TOOL_DECLARATIONS` — `types.Tool` with 4 `FunctionDeclaration` objects:
  - `regex_search(pattern)` → returns matches with line numbers
  - `replace_line(line_number, new_content, expected_content)` → replaces a line
  - `delete_line(line_number, expected_content)` → deletes a line
  - `add_line(after_line, new_content)` → inserts a line
- `_build_user_message(instruction, file_content)` — formats instruction + numbered file content
- `_build_file_state_message(file_content)` — formats updated file state after edits

**Verification:** Import the module, check tool declarations are valid, test message formatting.

## Step 2: Agent loop, tool dispatch, wire into `edit_file()`

**File: `src/agentic_editor/agent.py`** (additions)

- `run_agent()` async function — the core loop:
  1. Create client + FileEditor + ChangeReport
  2. Build initial message with instruction + numbered file
  3. Call `client.aio.models.generate_content()` with system prompt + tools + temperature=0
  4. If response has function calls → dispatch to FileEditor methods, build `FunctionResponse` parts, include updated file state, append to conversation history, repeat
  5. If response is text only (starts with "DONE:" or "ERROR:") → loop ends
  6. Safety caps: `MAX_AGENT_TURNS = 20`, `max_retries = 3` consecutive tool errors
- `_dispatch_tool()` — routes tool name to handler, catches `LineNumberError`/`ContentMismatchError`/`re.error` and returns error dicts for the LLM to retry
- `_handle_regex_search()`, `_handle_replace()`, `_handle_delete()`, `_handle_add()` — execute on FileEditor, record changes in ChangeReport

**File: `src/agentic_editor/__init__.py`** (modify lines 62-65)

- Replace stub with: `from agentic_editor.agent import run_agent; return await run_agent(...)`

**File: `tests/test_api.py`** (modify)

- Mock `agentic_editor.agent.run_agent` so existing unit tests pass without an API key

**Verification:** Run existing tests (should still pass with mocks). Manually test with a real API key.

## Step 3: Integration tests + dotenv setup

**File: `tests/test_integration.py`** (create)

- `pytestmark = pytest.mark.skipif(not GEMINI_API_KEY)` — skips when no key
- `test_simple_replace()` — replace a word on a specific line
- `test_delete_line()` — delete a line by content
- `test_add_line()` — add a line after a target
- `test_no_changes_needed()` — handle instruction where target doesn't exist

**File: `tests/conftest.py`** (create)

- `load_dotenv()` to load `.env` for tests

**File: `pyproject.toml`** (modify)

- Add `python-dotenv` to dev dependencies

**Verification:** `pytest tests/test_integration.py -v` with API key loaded from .env.

## Files Modified/Created

| File | Action |
|------|--------|
| `src/agentic_editor/agent.py` | Rewrite (steps 1-2) |
| `src/agentic_editor/__init__.py` | Modify stub → real call (step 2) |
| `tests/test_api.py` | Add mock for run_agent (step 2) |
| `tests/test_integration.py` | Create (step 3) |
| `tests/conftest.py` | Create (step 3) |
| `pyproject.toml` | Add python-dotenv dev dep (step 3) |
