# Context-Efficient Agent Redesign

## Purpose

This document describes an exact redesign of the current agent loop so the full file content is kept in Python memory and is **not** injected into the LLM context on every turn.

The goal is to make the package viable for larger files, reduce token usage, and better match the intended Thinglink workflow:

- upstream evaluator agents identify the exact issue
- this tool receives a literal instruction
- the LLM locates the target
- Python executes the surgical edit deterministically


## Problem In The Current Design

Right now the file content is sent directly to Gemini:

- once in the initial user message
- again after each tool call as a full "updated file state"
- again on every subsequent API call because the whole conversation history is resent

This means the current system is **context-heavy**, especially for multi-turn edits. A file with thousands of lines can become expensive. A file with tens of thousands of lines can become impractical.

Regex tools do not fix this on their own if the full file is still pasted into the prompt.


## Core Redesign Principle

The file should exist only inside Python for the duration of one `edit_file(...)` request.

- The caller passes `content` into Python.
- Python stores that content in memory in `FileEditor`.
- Gemini never sees the full file by default.
- Gemini interacts with the file only through tools.

This is temporary in-memory state, not permanent storage:

- no database
- no disk cache
- no persistent file write unless the caller later chooses to save the returned result


## Design Goals

- Do not send full file content to the model by default.
- Keep the editing workflow deterministic.
- Preserve content verification before edits.
- Support explicit, literal instructions as the primary mode.
- Allow limited local inspection through tools when instructions are not perfectly specific.
- Keep the public API simple.
- Make large-file behavior predictable and bounded.


## Non-Goals

- Deep semantic understanding of very large files.
- Autonomous debugging or validation of content correctness across an entire file.
- Permanent file storage or remote file access.
- Full-file summarization by the LLM.


## Proposed Public API

The public entrypoint can remain mostly unchanged:

```python
async def edit_file(
    instruction: str,
    content: str,
    *,
    model: str = "gemini-2.5-flash",
    report: bool = True,
    max_retries: int = 3,
    max_turns: int = 20,
) -> EditResult:
    ...
```

### Why keep the API simple

The caller should not need to care whether the file is passed into the prompt or held in memory. That is an internal execution detail.

The only optional API additions worth considering are:

```python
async def edit_file(
    instruction: str,
    content: str,
    *,
    model: str = "gemini-2.5-flash",
    report: bool = True,
    max_retries: int = 3,
    max_turns: int = 20,
    max_search_results: int = 20,
    context_window_lines: int = 3,
) -> EditResult:
    ...
```

- `max_search_results`: caps noisy search outputs
- `context_window_lines`: controls how many nearby lines a context tool returns

These can also remain internal constants initially if a smaller public API is preferred.


## Proposed Initial Prompt

The initial prompt should no longer include the full file.

It should include only:

- the instruction
- a short explanation of the tool workflow
- lightweight metadata about the file

Example structure:

```text
Instruction: Replace "93 billion miles" with "93 million miles".

You do not have the full file contents.
Use tools to search and inspect the file before editing.
Always verify the target line content before replacing or deleting.

File metadata:
- total_lines: 842
- approximate_chars: 31874
```

Optional metadata:

- file extension or media type if known
- whether the file appears to be JSON, HTML, Markdown, or plain text

This keeps the model oriented without paying the cost of the full file body.


## Proposed Tool Set

The current 4 tools are not enough for a context-efficient loop. The model needs small retrieval tools.

### 1. `regex_search(pattern, max_results=20)`

Purpose:
- locate candidate lines without exposing the whole file

Returns:

```json
{
  "status": "success",
  "matches": [
    {
      "line_number": 117,
      "match_text": "\"planet_count\": 7",
      "line_preview": "  \"planet_count\": 7,"
    }
  ],
  "total_matches": 1,
  "truncated": false
}
```

Notes:

- `line_preview` should be included because it helps the LLM decide next steps without another call in simple cases.
- Preview should be capped in length if needed.
- `max_results` prevents giant tool outputs.


### 2. `get_line(line_number)`

Purpose:
- inspect one exact line when search results are ambiguous or the instruction already specifies a location

Returns:

```json
{
  "status": "success",
  "line_number": 117,
  "content": "  \"planet_count\": 7,"
}
```


### 3. `get_lines(start_line, end_line)`

Purpose:
- inspect a small local region around a match
- useful for JSON blocks, HTML sections, and Markdown lists

Returns:

```json
{
  "status": "success",
  "lines": [
    {"line_number": 115, "content": "  \"title\": \"The Solar System\","},
    {"line_number": 116, "content": "  \"description\": \"...\","},
    {"line_number": 117, "content": "  \"planet_count\": 7,"},
    {"line_number": 118, "content": "  \"star\": \"The Sun\""}
  ]
}
```

Notes:

- `get_lines` should be bounded to a small maximum range, for example 20-50 lines.
- If the requested range is too large, Python should return an error and instruct the model to narrow the request.


### 4. `replace_line(line_number, new_content, expected_content)`

Purpose:
- deterministic replace with content verification

No conceptual change from the current design.


### 5. `delete_line(line_number, expected_content)`

Purpose:
- deterministic delete with content verification

No conceptual change from the current design.


### 6. `add_line(after_line, new_content)`

Purpose:
- deterministic line insertion

No conceptual change from the current design.


## Optional Later Tools

These are not necessary for the first redesign pass, but may become useful.

### `get_match_context(line_number, before=2, after=2)`

This is a convenience wrapper around `get_lines(...)`.

### `replace_span(start_line, end_line, new_lines, expected_lines)`

Useful for multi-line JSON or HTML edits, but it adds complexity and should not be part of the first redesign unless required.

### `find_unique_match(pattern)`

Could enforce that a search must produce exactly one match, but this is likely unnecessary if the LLM can handle normal search results.


## Recommended First-Pass Tool Schema

For the first implementation pass, the minimum good set is:

- `regex_search`
- `get_line`
- `get_lines`
- `replace_line`
- `delete_line`
- `add_line`

That is enough to support targeted edits without full-file prompt injection.


## Proposed Agent Workflow

### Initial state

Python creates:

- `FileEditor(content)`
- `ChangeReport()` if reporting is enabled
- compact initial message with instruction and metadata

### Iteration pattern

1. Gemini reads the instruction and available tools.
2. Gemini calls `regex_search(...)` to locate a likely target.
3. If needed, Gemini calls `get_line(...)` or `get_lines(...)` for local context.
4. Gemini calls `replace_line(...)`, `delete_line(...)`, or `add_line(...)`.
5. Python executes the edit deterministically.
6. Python returns:
   - tool result
   - maybe a small local post-edit confirmation
   - not the full updated file
7. Gemini either continues with another small search/inspection/edit cycle or returns `DONE:`.


## Critical Change To The Conversation Model

The current code appends the full updated file state after each tool call. That should be removed.

Instead:

- retrieval tools provide local context when needed
- edit tools return only compact results
- the model asks for more context explicitly if it needs it

Example edit tool response:

```json
{
  "status": "success",
  "before": "  \"planet_count\": 7,",
  "after": "  \"planet_count\": 8,",
  "line_number": 117
}
```

Optional addition:

```json
{
  "status": "success",
  "before": "  \"planet_count\": 7,",
  "after": "  \"planet_count\": 8,",
  "line_number": 117,
  "nearby_lines": [
    {"line_number": 116, "content": "  \"description\": \"...\","},
    {"line_number": 117, "content": "  \"planet_count\": 8,"},
    {"line_number": 118, "content": "  \"star\": \"The Sun\""}
  ]
}
```

This should be optional and tightly bounded.


## Changes Needed In `FileEditor`

`FileEditor` already holds the file in memory, which is good. It needs a few read-oriented methods:

```python
def get_line(self, line_number: int) -> str: ...

def get_lines(self, start_line: int, end_line: int) -> list[tuple[int, str]]: ...

def regex_search(
    self,
    pattern: str,
    *,
    max_results: int = 20,
    preview_chars: int = 200,
) -> RegexSearchResult:
    ...
```

Recommended behaviors:

- validate ranges carefully
- cap output sizes
- return truncation metadata when search results are clipped


## Changes Needed In Tool Dispatch

Add new handlers:

- `_handle_get_line(...)`
- `_handle_get_lines(...)`

Update existing handlers so they:

- return compact results only
- do not attach full-file state

Keep current error handling:

- invalid regex
- line out of range
- content mismatch
- max consecutive errors


## Changes Needed In The System Prompt

The system prompt should explicitly teach the new workflow:

- you do not have the full file
- search first
- inspect small context if needed
- never guess line numbers
- always provide `expected_content` for replace/delete
- do not request large ranges unless necessary
- finish with `DONE:`

This is important because the model must understand that local retrieval is now mandatory.


## Change Report Implications

The report design does not need major structural change.

Current fields still fit:

- `line_numbers`
- `operation`
- `before`
- `after`
- `reason`

However, the `reason` field should ideally become more useful than placeholder text like `"Replaced line 17"`.

Recommended direction:

- capture a concise agent-provided reason if available
- otherwise use a deterministic fallback generated by Python

This is separate from the context-efficiency redesign, but worth addressing while touching the loop.


## Behavior For Literal Instructions

This redesign fits the intended Thinglink use case well.

Example:

Instruction:

```text
Replace "93 billion miles" with "93 million miles" in the paragraph about the Sun.
```

Likely tool flow:

1. `regex_search("93 billion miles|Sun")`
2. `get_lines(...)` around a candidate
3. `replace_line(...)`
4. `DONE: fixed incorrect distance value`

The model does not need the entire file. It only needs enough local context to safely identify the target.


## Behavior For Vague Instructions

The redesign still allows limited recovery if instructions are not perfect.

Example:

```text
There is a typo in the second module title. Fix it.
```

Possible flow:

1. `regex_search("module|title")`
2. `get_lines(...)`
3. more targeted `regex_search(...)`
4. edit

This is acceptable as fallback behavior, but the system should still be optimized for explicit instructions, not broad autonomous analysis.


## Expected Benefits

- Large reduction in prompt size per turn
- Much better scalability for medium and large files
- Better alignment with "tool agent" behavior
- Lower token cost
- More predictable failure modes


## Tradeoffs

- More tool calls may be needed for some edits
- The model must be prompted carefully to inspect context deliberately
- Some vague tasks may become slightly slower because the model no longer sees the whole file immediately

This tradeoff is acceptable because the primary workflow is targeted, literal edits.


## Suggested Implementation Order

### Step 1: Add bounded read tools

- implement `get_lines(...)`
- ensure `get_line(...)` is available through tool dispatch
- add result-size limits to `regex_search(...)`

### Step 2: Remove full-file prompt injection

- stop passing full content in `_build_user_message(...)`
- replace it with instruction + metadata

### Step 3: Remove full updated-file resend

- delete `_build_file_state_message(...)` from the loop
- do not attach full file state to tool responses

### Step 4: Update system prompt and tool schemas

- teach the new retrieval-first behavior
- add schemas for `get_line` and `get_lines`

### Step 5: Update tests

- add unit tests for read tools
- update integration tests to confirm the new flow still succeeds
- add tests for large result truncation and oversized line-range requests

### Step 6: Update docs

- explain that file content stays in Python memory during one request
- explain that large files are supported better, but still constrained by tool-result size and total turn count


## Testing Strategy

### Unit tests

- `get_lines(...)` range validation
- `regex_search(...)` result truncation
- edit operations still enforce content verification
- line shifts still behave correctly after edits

### Integration tests

- simple replace using search plus local context
- delete a line by content
- add a line after a target line
- multi-edit JSON update
- medium-size file with no full-file prompt injection

### Future stress tests

- synthetic file with thousands of lines
- repeated edits spread far apart
- ambiguous search results requiring local inspection


## Open Questions

- Should `line_preview` in `regex_search(...)` return the full line or a capped preview?
- Should `get_lines(...)` allow up to 20 lines, 50 lines, or be configurable?
- Do we want file-type hints in the prompt if the caller does not provide a filename?
- Should we later add multi-line edit tools, or keep line-based editing only?


## Recommendation

Implement this redesign.

It keeps the package aligned with the actual product requirement: a narrow, deterministic editing tool for explicit instructions. It also avoids the main scalability weakness of the current implementation, which is repeatedly sending the full file through the model context.
