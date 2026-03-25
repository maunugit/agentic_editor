# CLAUDE.md

## Project Overview

Standalone async Python package ("agentic-editor") that takes a natural-language instruction + plain-text file content, uses an LLM agent with regex tools to perform line-by-line edits (replace, delete, add), and returns the edited file + a structured JSON change report.

Built by Team UEF (Maunu, Aaya, Qamar) for Thinglink's Scenario Builder pipeline. See `AGENT_EDITING_FRAMEWORK_BRIEF.md` for the full project brief and `ROADMAP.md` for phased implementation plan.

## Key Design Decisions

- **Regex is a search tool only.** The LLM generates regex patterns to locate lines. Python executes the patterns and returns matches with line numbers. The LLM never executes regex directly.
- **Edits are deterministic.** The LLM decides what to do (replace/delete/add), Python executes the edit. The `before`/`after` in the change report are captured from actual file text, not LLM output.
- **Content verification before edits.** Before executing an edit, verify that the target line's content matches what the agent expects — not just that the line number exists.
- **Updated file state after each edit.** The agent loop feeds the agent the current file state after each edit, not the original, to avoid stale line number references.
- **Max retries on tool errors.** Invalid regex or failed matches should be reported back to the agent for retry, with a cap (3-5 attempts) to prevent infinite loops.
- **Small files first.** Build for reasonably sized files (hundreds to low thousands of lines). Large-file handling deferred until we know Thinglink's actual file sizes.

## Tech Stack

- **Language:** Python, async
- **LLM:** Gemini 2.5 Flash (default), with option to test Gemini 2.5 Pro. SDK: `google-genai`
- **Testing:** pytest, pytest-asyncio
- **Package format:** `pyproject.toml`, installable via `pip install git+https://...`

## Project Structure

```
agentic_editor/
├── CLAUDE.md
├── AGENT_EDITING_FRAMEWORK_BRIEF.md
├── ROADMAP.md
├── PHASE3.md                    # Phase 3 implementation plan
├── pyproject.toml
├── .env                         # GEMINI_API_KEY (not committed)
├── src/
│   └── agentic_editor/
│       ├── __init__.py          # public API (edit_file)
│       ├── agent.py             # agent loop, Gemini client, system prompt, tool declarations
│       ├── tools.py             # FileEditor: regex search, replace, delete, add
│       └── models.py            # data models (ChangeEntry, ChangeReport, EditResult)
└── tests/
    ├── conftest.py              # loads .env for tests
    ├── test_tools.py            # FileEditor unit tests
    ├── test_models.py           # data model unit tests
    ├── test_api.py              # public API unit tests (mocked, no API key needed)
    └── test_integration.py      # live Gemini API tests (skipped without GEMINI_API_KEY)
```

## Current agent loop (run_agent()):
1. We send the conversation to Gemini with our tool declarations (FunctionDeclaration)
2. Gemini responds. We check if the response contains `function_call` parts.
3. If yes -> Gemini is saying "I want to call `regex_search(pattern="DELETE ME")` but it didn't actually call anything, it's just a request. Then, we:
    - Read `fc.name` and `fc.args` from the response
    - Route it through `_dispact_tool()` from the response
    - Route it on our `FileEditor`
    - Record change in `ChangeReport``
    - Count errors for retry logic
    - Build a `FunctionResponse` part with the result + updated file state
    - Append everything to conversation history
    - Loop back to step 1
4. If no function calls (just text like "DONE: replaced...") the agent is finished, exit loop

Now, in the middle of every tool call, we can track changes, count errors, cap total turns, feed updated file state, verify content, and so on.
This is why agent.py uses FunctionDeclaration, not AFC (Automatic Function Calling) from the SDK. If AFC is enabled, the SDK itself intercepts the models request, calls our function, sends the result back to the model, and loops, this happens in a black box independently, we can't control it. But with FunctionDeclaration, it's like a description of what a function looks like. There's no actual Python function attached. The SDK can't auto-call anything because there's nothing to call. So `generate_content()` simply returns function call requests in the response.

## Commands

- Run all unit tests (no API key needed): .venv/bin/python -m pytest tests/test_tools.py tests/test_models.py tests/test_api.py -v
- Run integration tests (needs GEMINI_API_KEY in .env): .venv/bin/python -m pytest tests/test_integration.py -v
- Run everything: .venv/bin/python -m pytest -v
- Venv launch: source .venv/bin/activate
- Individual test files:
  .venv/bin/python -m pytest tests/test_tools.py -v
  .venv/bin/python -m pytest tests/test_models.py -v
  .venv/bin/python -m pytest tests/test_api.py -v
  .venv/bin/python -m pytest tests/test_integration.py -v
