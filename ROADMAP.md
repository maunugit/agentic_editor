# Roadmap

## Phase 1 — Project Scaffolding & Core Data Models ✅

- [x] Set up Python package structure (`pyproject.toml`, `src/agentic_editor/`, `tests/`)
- [x] Define data models for the change report (operation types, change entries, final report)
- [x] Define the public API surface (what callers will import and call)
- [x] Set up basic test infrastructure (pytest, pytest-asyncio)

## Phase 2 — Edit Operations & Regex Tool ✅

- [x] Implement line-level edit operations: replace, delete, add
- [x] Build the regex tool (takes a pattern, executes against file content, returns matches with line numbers)
- [x] Add content verification before executing edits (confirm line content matches what the agent expects)
- [x] Handle line-number shifts when multiple edits occur in sequence
- [x] Unit tests for all operations and edge cases

## Phase 3 — Agent Loop & Gemini Integration ✅

> **Key design input (confirmed by Saif, 2026-03-24):** Instructions from Thinglink will be literal and specific — their upstream agents determine what needs fixing. Our agent's job is to locate and execute, not to analyze the file for errors. The system prompt and loop design should reflect this: the agent receives a clear instruction, uses regex to find the target lines, and performs the edit. It still needs enough intelligence to generate regex patterns and handle multi-match scenarios, but it does not need to reason about content correctness.

- [x] Set up Gemini API client (async) using `google-genai` Python SDK
- [x] Use `gemini-2.5-flash` as the default model, with option to test `gemini-2.5-pro` for comparison
- [x] Design the agent loop: prompt → reasoning → tool call → execute → repeat
- [x] Agent receives updated file state after each edit (not stale original)
- [x] Define the system prompt and tool descriptions for the LLM
- [x] Wire regex tool and edit operations into the agent's tool-calling flow
- [x] Integration tests with the live API



## Phase 4 — Change Report & Output

- Generate the structured JSON change report from recorded edits
- Add toggle to enable/disable report generation
- Ensure `before`/`after` fields are captured deterministically from actual text
- End-to-end tests: instruction + file in → edited file + report out

## Phase 5 — Documentation & Packaging

- Document public API with usage examples
- Document max API costs / token usage in edge cases
- Document errors raised and known limitations
- Ensure the package is installable via `pip install git+https://...`
- Final review and cleanup
