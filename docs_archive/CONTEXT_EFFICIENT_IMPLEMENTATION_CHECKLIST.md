# Context-Efficient Implementation Checklist

## Scope

This checklist turns the redesign in [CONTEXT_EFFICIENT_AGENT_REDESIGN.md](/Users/maunu/agentic_editor/CONTEXT_EFFICIENT_AGENT_REDESIGN.md) into concrete implementation work for the current repo.

The goal is to remove full-file prompt injection and move to a retrieval-first tool loop where:

- file content stays in Python memory
- Gemini sees only the instruction plus compact metadata
- Gemini retrieves local context through tools
- edit tools remain deterministic


## Phase A: Update Core Design Constants

### `src/agentic_editor/__init__.py`

- [x] Change the default `model` back to the documented default if needed.
- [x] Ensure the docstring and function argument docs match the actual default model.
- [x] Decide whether `max_turns`, `max_search_results`, or `context_window_lines` should be public API params now or internal constants for the first pass.

Success criteria:

- public API docs match implementation
- no stale mention of full-file prompt behavior


### `src/agentic_editor/agent.py`

- [x] Replace the current default `model` if the project should standardize on `gemini-2.5-flash`.
- [x] Add internal constants for:
  - [x] `MAX_AGENT_TURNS`
  - [x] `MAX_SEARCH_RESULTS`
  - [x] `MAX_GET_LINES_RANGE`
  - [x] `LINE_PREVIEW_CHARS`
- [x] Keep initial defaults conservative and easy to tune.

Success criteria:

- core behavior limits are explicit and centralized


## Phase B: Extend `FileEditor` With Read Tools

### `src/agentic_editor/tools.py`

- [x] Add a bounded `get_lines(start_line, end_line)` method.
- [ ] Decide whether to return:
  - [ ] plain tuples internally, or
  - [x] a small dataclass for line snapshots
- [x] Validate line ranges carefully:
  - [x] reject `start_line < 1`
  - [x] reject `end_line < start_line`
  - [x] reject `end_line > line_count`
- [x] Add a maximum range guard so the model cannot request an excessively large block.
- [x] Update `regex_search(...)` to support:
  - [x] `max_results`
  - [x] preview truncation
  - [x] `total_matches`
  - [x] `truncated`
- [x] Keep existing deterministic edit methods unchanged unless small refactors are needed.

Optional:

- [x] Add a small helper for line preview truncation.

Success criteria:

- Python can serve local file context without sending full content to the model
- search outputs are compact and bounded


## Phase C: Redesign Tool Schemas

### `src/agentic_editor/agent.py`

- [x] Add `FunctionDeclaration` entries for:
  - [x] `get_line`
  - [x] `get_lines`
- [ ] Update `regex_search` schema to include optional `max_results` if exposed to the model.
- [x] Keep `replace_line`, `delete_line`, and `add_line`.
- [x] Review descriptions so the model clearly understands:
  - [x] it does not have full file visibility
  - [x] it must search or inspect before editing
  - [x] it must use `expected_content` for replace/delete

Success criteria:

- tool menu is sufficient for retrieval-first operation
- schema descriptions teach the intended workflow


## Phase D: Replace Full-File Initial Prompt

### `src/agentic_editor/agent.py`

- [x] Rewrite `_build_user_message(...)` so it does not include numbered file content.
- [x] Replace it with:
  - [x] instruction
  - [x] explicit note that the full file is not available by default
  - [x] compact file metadata
- [x] Decide which metadata to include:
  - [x] `total_lines`
  - [x] `approximate_chars`
  - [ ] maybe a lightweight guessed file type

Success criteria:

- initial prompt is compact
- no full file text is injected into the first turn


## Phase E: Remove Full Updated File State Resend

### `src/agentic_editor/agent.py`

- [x] Remove `_build_file_state_message(...)` or stop using it.
- [x] Remove `current_file_state` from tool responses.
- [x] Ensure tool responses contain only compact information.
- [ ] If helpful, allow edit tools to return a very small local confirmation payload, but not a full-file dump.

Success criteria:

- no turn re-sends the full file after edits
- model must ask for local context explicitly through tools


## Phase F: Add Tool Dispatch For Read Operations

### `src/agentic_editor/agent.py`

- [x] Add `_handle_get_line(...)`.
- [x] Add `_handle_get_lines(...)`.
- [x] Update `_dispatch_tool(...)` to route the new tools.
- [ ] Return consistent response shapes for all tools.
- [x] Preserve existing error handling for:
  - [x] invalid regex
  - [x] out-of-range lines
  - [x] content mismatch
- [x] Add an error path for oversized `get_lines(...)` requests.

Success criteria:

- agent can inspect exact lines and bounded line ranges through tools
- failures are compact and retryable


## Phase G: Update The System Prompt

### `src/agentic_editor/agent.py`

- [x] Rewrite `SYSTEM_PROMPT` to reflect the new workflow.
- [x] Explicitly state:
  - [x] you do not have the full file
  - [x] always search or inspect before editing
  - [x] never guess line numbers
  - [ ] use small context windows
  - [x] use `expected_content` for replace/delete
  - [x] return `DONE:` when finished
  - [x] return `ERROR:` if the instruction cannot be completed

Success criteria:

- prompt teaches retrieval-first behavior clearly
- prompt matches actual tool semantics


## Phase H: Tighten Agent Loop Behavior

### `src/agentic_editor/agent.py`

- [x] Review how the loop handles a non-tool text response.
- [x] Decide whether to:
  - [x] require `DONE:` or `ERROR:`
  - [x] surface the final model message in result metadata
- [x] Review the `max_retries` path that currently returns partial output silently.
- [x] Decide whether to:
  - [x] keep partial-return behavior
  - [ ] raise a structured error
  - [x] include failure status in the result model

Implementation decision:

- `EditResult` now carries structured terminal state via `status`, `final_message`, and `completed`.
- Partial content is still returned on incomplete runs, but it is explicitly marked as incomplete.
- Non-tool plain-text responses are only accepted as terminal when they begin with `DONE:` or `ERROR:`.

This is not strictly required for context efficiency, but it is worth addressing while touching the loop.

Success criteria:

- loop termination behavior is explicit and defensible


## Phase I: Improve Change Report Recording

### `src/agentic_editor/agent.py`

- [ ] Review the `reason` field currently recorded as generic placeholder text.
- [ ] Decide whether first pass should:
  - [ ] keep deterministic placeholder reasons, or
  - [ ] allow the model to include a short reason in tool args
- [ ] If changing tool args now feels too broad, keep current behavior and document it.

Success criteria:

- change report behavior is intentional, not accidental


## Phase J: Unit Tests For Read Tools

### `tests/test_tools.py`

- [x] Add tests for `get_line(...)` if needed beyond current coverage.
- [x] Add tests for `get_lines(...)`:
  - [x] valid bounded range
  - [x] start/end validation
  - [x] end before start
  - [x] out-of-range requests
  - [x] oversized range rejection
- [x] Add tests for updated `regex_search(...)` behavior:
  - [x] `max_results`
  - [x] `total_matches`
  - [x] `truncated`
  - [x] preview truncation if implemented

Success criteria:

- new read-path behavior is covered locally without API calls


## Phase K: Unit Tests For Agent Helpers

### `tests/test_api.py`

- [x] Keep API contract tests working with mocked `run_agent`.
- [x] Add tests if public API parameters change.


### new or existing agent-focused tests

- [x] Add tests for compact initial prompt generation.
- [x] Add tests that confirm the full file content is not embedded in the initial user message.
- [x] Add tests for `_dispatch_tool(...)` on:
  - [x] `get_line`
  - [x] `get_lines`
  - [x] oversized range rejection
- [x] Add tests for terminal text handling and safety-cap exits:
  - [x] valid `DONE:`
  - [x] valid `ERROR:`
  - [x] invalid plain-text protocol response
  - [x] max retries
  - [x] max turns

Note:

- [x] If `agent.py` helper functions are currently hard to test cleanly, consider adding a focused `tests/test_agent.py`.

Success criteria:

- the most important context-efficiency behavior is testable without live Gemini calls


## Phase L: Integration Tests

### `tests/test_integration.py`

- [ ] Keep existing edit scenarios:
  - [ ] simple replace
  - [ ] delete
  - [ ] add
  - [ ] no-op or no-match flow
  - [ ] JSON fixes
  - [ ] HTML fixes
  - [ ] Markdown fixes
- [ ] Add at least one test that exercises the retrieval-first flow on a medium-size file.
- [ ] Add one integration test where the target requires local context inspection, not only a single exact match.

Success criteria:

- the redesign still works end-to-end with live Gemini
- behavior remains stable across file formats


## Phase M: Documentation Updates

### `README.md`

- [ ] Update the "How It Works" section to reflect retrieval-first context access.
- [ ] Remove any implication that the full file is always sent to the model.
- [ ] Document that file content stays in Python memory during a request.
- [ ] Add a short note on scalability:
  - [ ] better for medium and large files than the previous design
  - [ ] still bounded by total turns and tool output limits
- [ ] Reconcile the default model name with implementation.


### `AGENTS.md`

- [ ] Update the session/project description if the architecture changes materially.
- [ ] Add a note that the file is held in Python memory and exposed through retrieval tools, not injected wholesale into the prompt.


### `ROADMAP.md`

- [ ] Add this redesign as a concrete item under Phase 4 or Phase 5, depending on how you want to classify it.
- [ ] Update completion status once implementation lands.

Success criteria:

- repo docs describe the actual architecture, not the old one


## Phase N: Nice-To-Have Cleanup

### `src/agentic_editor/models.py`

- [ ] Clean up overly explanatory inline comments if they are no longer helpful.
- [ ] Keep docstrings concise and package-level.


### `src/agentic_editor/tools.py`

- [ ] Clean up typos and comment noise while editing nearby code.


### `src/agentic_editor/agent.py`

- [ ] Remove dead helper code after `_build_file_state_message(...)` is retired.

Success criteria:

- touched files are cleaner after the redesign, not more cluttered


## Proposed Execution Order

- [x] 1. Extend `FileEditor` with bounded read methods and search result limits.
- [x] 2. Add new tool schemas and dispatch handlers.
- [x] 3. Rewrite the initial prompt to use instruction plus metadata only.
- [x] 4. Remove full updated-file resend from the loop.
- [x] 5. Update the system prompt.
- [x] 6. Add or update unit tests.
- [x] 7. Run unit tests.
- [ ] 8. Run integration tests if `GEMINI_API_KEY` is available.
- [ ] 9. Update docs.


## Review Gates Before Merging

- [x] Full file content is no longer sent in the first prompt.
- [x] Full file content is no longer appended after each tool call.
- [x] New retrieval tools are bounded and tested.
- [x] Deterministic edit operations still use content verification.
- [x] Existing API remains simple.
- [x] Unit tests pass.
- [ ] Integration tests pass or are explicitly noted as not run.
- [ ] Docs match implementation.
