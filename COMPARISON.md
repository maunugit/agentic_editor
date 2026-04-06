# Agentic Editor — Branch Comparison & Merge Strategy

**Branches:** `aaya_dev` (this branch) vs `main` (Maunu + Qamar's redesign)  
**Purpose:** Document what each branch does, where they agree, where they differ, and how the best version of the package is a merge of both.

---

## What both branches agree on (shared foundation)

These decisions are identical across both branches and should be kept as-is in any merge:

- **FunctionDeclaration over AFC** — Gemini does not auto-call tools. It returns a function call request, we execute it, we send back the result. Full control of the loop.
- **`FileEditor` as the execution layer** — regex search, replace, delete, add are all deterministic Python. The LLM never executes code directly.
- **Content verification before edits** — `expected_content` is required on replace and delete so the agent can't silently edit the wrong line.
- **`ChangeReport` + `ChangeEntry`** — structured JSON report of every edit with before/after captured from actual file text, not LLM output.
- **`temperature=0.0`** — fully deterministic for editing tasks.
- **`MAX_AGENT_TURNS = 20`** — hard cap on API calls to prevent infinite loops.
- **`max_retries`** — consecutive tool error cap before giving up.
- **Public API shape** — `edit_file(instruction, content, ...)` returning `EditResult`.

---

## Key differences

### 1. Completion signal

| | `aaya_dev` | `main` |
|---|---|---|
| **Mechanism** | `finish_editing` tool with `status: enum["done", "error"]` | Plain text `DONE: ...` / `ERROR: ...` parsed with `startswith()` |
| **Reliability** | Gemini API enforces the enum — model physically cannot pass anything other than `"done"` or `"error"` | `startswith()` breaks when Gemini adds filler text (`"I've completed all edits. DONE: ..."`) — triggers `protocol_error` |
| **Fallback** | If model outputs plain text, `break` exits the loop with `status="incomplete"` | `_build_terminal_result()` tries to parse text, falls through to `protocol_error` |

**Why `finish_editing` wins:** It's a structured tool call. The API validates the enum value before the response even reaches our code. Text parsing is inherently fragile with LLMs because the model is a next-token predictor — it can and does add context before the keyword.

---

### 2. Initial file message

| | `aaya_dev` | `main` |
|---|---|---|
| **What's sent** | Full numbered file content (`1: line one\n2: line two\n...`) | Only metadata (`total_lines`, `approximate_chars`) |
| **Model sees file** | Immediately in context | Only via `regex_search`, `get_line`, `get_lines` calls |
| **Token cost** | Higher — entire file on every turn | Lower — only fetched lines |
| **Simplicity** | One system — works the same for every file | One system — also works the same for every file |

**Why metadata-first is better for larger files:** Sending a 500-line file on every single turn inflates the conversation history fast. On turn 15, you're sending the same 500 lines 15 times. Retrieval-first avoids this. For small files the difference is negligible, but the principle is cleaner and scales better.

**Counter-argument for full injection:** The model can see all context immediately without tool round-trips. On a 20-line file, the extra `get_line` call costs a full API round-trip just to read a line the model could have had for free.

**Proposed resolution:** Keep metadata-first (Maunu's approach) but add the `get_lines` retrieval tool so the model can explicitly read any range it needs. This is already in `main`.

---

### 3. `reason` field on edit tools

| | `aaya_dev` | `main` |
|---|---|---|
| **Declaration** | Required — `required=["line_number", "new_content", "expected_content", "reason"]` | Optional — not in `required` list |
| **Fallback** | None — if Gemini skips it, the field is empty string | Deterministic fallback: `"Replace: 'old' -> 'new'"` |
| **Audit quality** | Gemini always provides a meaningful reason | Guaranteed non-empty but may be auto-generated |

**Why required + no fallback is slightly better:** The reason field is the main human-readable record of why an edit happened. Making it required forces the model to think about it. An empty reason is worse than a generated one, but a generated reason (`"Replace: 'x' -> 'y'"`) tells you nothing you couldn't read from `before`/`after` anyway.

**Proposed resolution:** Keep required, but add Maunu's deterministic fallback as a safety net for the rare case Gemini ignores a required field. Belt and suspenders.

---

### 4. One function call per turn

| | `aaya_dev` (before fix) | `aaya_dev` (after fix, this branch) | `main` |
|---|---|---|---|
| **Behavior** | Execute ALL function calls in one response | Execute only FIRST function call | Execute only FIRST function call |

Both branches now agree here. Executing multiple fcs in one turn is unsafe because the second edit uses line numbers from before the first edit ran — the file has shifted.

---

### 5. Retrieval tools (`get_line`, `get_lines`)

| | `aaya_dev` | `main` |
|---|---|---|
| **Tools** | `regex_search` only | `regex_search` + `get_line` + `get_lines` |
| **Rationale** | `regex_search` returns `line_content` on every match — the model already "reads" the line | `get_line` allows post-edit verification; `get_lines` reads local context without a search |

**Assessment:** `get_line` is genuinely useful for the metadata-first approach — if the model needs to read a specific line it already knows the number for, running `regex_search` just to read it is wasteful. Worth adding if metadata-first is adopted.

---

### 6. Input validation

| | `aaya_dev` | `main` |
|---|---|---|
| **Binary guard** | `_is_binary()` in `__init__.py` — blocks binary before any API call | Not present |
| **Arg type checking** | `int(args["line_number"])` — silent cast, crashes on bad type | `_require_int_arg()` / `_require_str_arg()` — explicit error returned to model for retry |

**Binary guard:** Worth keeping in any merge. Passing a PNG as a string would silently produce garbage without it.  
**Arg type checking:** Maunu's approach is more robust — casting with `int()` on a stringified integer will "work" but passing a string like `"not-a-number"` crashes instead of returning an error the model can retry.

---

### 7. Status granularity on `EditResult`

| | `aaya_dev` | `main` |
|---|---|---|
| **Status values** | `"done"`, `"error"`, `"incomplete"` | `"done"`, `"error"`, `"incomplete_max_turns"`, `"incomplete_max_retries"`, `"protocol_error"` |
| **Extra fields** | None | `completed: bool`, `final_message: str` |

**Assessment:** More granular status is better for callers — `"incomplete_max_turns"` and `"incomplete_max_retries"` tell you why it stopped. `completed: bool` is a convenient shorthand. These are additive and non-breaking.

---

### 8. Test quality

| | `aaya_dev` | `main` |
|---|---|---|
| **Integration tests** | Verify `before`, `after`, `reason`, `operation` on every test | Check only presence (`report is not None`, `len >= 1`) |
| **Unit tests (agent)** | None | `test_agent.py` — full agent loop tested with fake Gemini client |
| **Binary guard tests** | Yes | No |

**Assessment:** Both test suites complement each other. `aaya_dev`'s integration assertions are stronger. `main`'s `test_agent.py` is essential — it tests the loop logic without an API key using monkeypatched fake clients. The ideal test suite includes both.

---

## Proposed merge strategy

The best version of this package combines:

| Feature | Take from | Notes |
|---|---|---|
| `finish_editing` enum tool | `aaya_dev` | Replace `DONE:`/`ERROR:` text protocol |
| Metadata-first initial message | `main` | Scales better than full file injection |
| `get_line` + `get_lines` retrieval tools | `main` | Needed to complement metadata-first |
| One-fc-per-turn loop | Both | Now fixed in `aaya_dev` too |
| `reason` required + deterministic fallback | Both | Required from `aaya_dev`, fallback from `main` |
| `_is_binary()` binary guard | `aaya_dev` | Missing from `main` |
| `_require_int_arg` / `_require_str_arg` | `main` | Better arg validation |
| Granular status constants | `main` | `incomplete_max_turns`, `protocol_error`, etc. |
| `completed` + `final_message` on `EditResult` | `main` | Additive, non-breaking |
| `TraceCallback` | `main` | Observability, additive |
| Integration test assertions (before/after/reason) | `aaya_dev` | Stronger than presence-only checks |
| `test_agent.py` unit tests | `main` | Loop tested without API key |
| Binary guard tests | `aaya_dev` | Missing from `main` |

The one genuine design choice to discuss with the team is **full file injection vs metadata-first**, since that determines whether `get_line`/`get_lines` are needed. Everything else is additive and non-conflicting.
