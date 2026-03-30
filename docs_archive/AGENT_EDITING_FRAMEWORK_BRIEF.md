# Agent-as-a-Tool Editing Framework — Project Brief

## Origin

This document summarizes the task assigned by Saif (Thinglink) to Team UEF (Maunu, Aaya, Qamar) as part of the broader Thinglink Scenario Builder project. This file is meant to be copied into the new project directory as a starting reference.

## Context: How This Fits Into Thinglink's Pipeline

Thinglink is building a multi-phase Scenario Builder:

- **Phase 1:** Chat agent understands user requirements, produces a scenario brief, converts it to a Markdown outline.
- **Phase 2:** Blocks are generated separately (text, media, question), connected together into a full course in Markdown. Two Evaluator Agents (structural/logical validation + content quality/coherence) review and loop back revisions if needed.
- **Phase 3:** Finalization — enhancement, media creation, QA, conversion to final format.

**Team TL** (Alexey, Saif, Anton) builds the overall framework and the QA/evaluator agents.
**Team UEF** (Maunu, Aaya, Qamar) builds the editing tool that those agents (and potentially other parts of the pipeline) can call.

The editing framework is intentionally independent — a standalone Python package that can be integrated anywhere in the pipeline without being coupled to Thinglink's internal codebase.

## Task Specification

Build an **Agent-as-a-tool editing framework** as a Python package.

### Inputs
- One generic natural-language instruction (string)
- One plain-text file (JSON, HTML, Markdown, Python, etc. — any format readable in a text editor)

### Requirements
- Support Gemini model API at minimum
- Work only with plain-text formats (no binary formats like images)
- Perform **line-by-line edits** — replace, delete, and add operations
- Use **regex as a tool** for the agents (LLM generates regex patterns, Python executes them)
- The package must be **async** in nature
- Free to use sequential, parallel, or looping agent workflows

### Outputs
1. The edited file itself
2. A structured JSON change report (toggleable — can be turned off):
```json
{
  "changes": [
    {
      "line_numbers": [12, 13],
      "operation": "replace/edit/remove",
      "before": "old content (captured deterministically from actual text)",
      "after": "new content (captured deterministically from actual text)",
      "reason": "e.g., fix invalid JSON syntax"
    }
  ]
}
```

### Documentation Requirements
- Document the package fully
- Include max API costs possible in edge cases
- Document errors raised
- Document any limitations or warnings

## How the Agent Loop Works (Conceptual)

1. The LLM agent receives the natural-language instruction and the file contents
2. The agent reasons about what needs to change
3. The agent calls a regex tool to **locate** relevant lines in the file
4. The agent decides the operation (replace, delete, add) and the new content
5. Python executes the edit deterministically (the LLM doesn't rewrite the before/after — it's captured from actual text)
6. The change is recorded in the report
7. Steps 3-6 repeat until all necessary edits are complete
8. The edited file and report are returned

## How the Agent Loop Actually Works (Implementation)

This describes what `run_agent()` in `agent.py` actually does. So the real version of the conceptual loop above.

### Setup
- A Gemini API client is created using `GEMINI_API_KEY` from the environment
- A `FileEditor` instance is created with the file content (this holds the mutable file state)
- A `ChangeReport` is initialized to record edits (unless `report=False`)
- The conversation history starts with a user message containing the instruction + the file content with numbered lines

### Tool Declarations (the "menu")
Link to docs: https://googleapis.github.io/python-genai/genai.html#genai.types.FunctionDeclaration 
We pass Gemini four tool schemas via `types.FunctionDeclaration`. They are not actual Python functions. This is important: because no real functions are attached, the SDK's **Automatic Function Calling (AFC)** is disabled. Gemini can request tool calls, but it can't execute them. Control returns to our code after every API response.

The four tools:
1. **`regex_search(pattern)`** — search all lines for a regex pattern, returns matches with line numbers
2. **`replace_line(line_number, new_content, expected_content)`** — replace a line (with content verification)
3. **`delete_line(line_number, expected_content)`** — delete a line (with content verification)
4. **`add_line(after_line, new_content)`** — insert a new line after a given line number

### The Loop

Each iteration (capped at `MAX_AGENT_TURNS = 20`):

1. **Call Gemini** — send the full conversation history + system prompt + tool schemas
2. **Check the response:**
   - If Gemini returned **function calls** → it wants to use tools. For each function call:
     a. Read the tool name and arguments from the response
     b. Route to the correct handler (`_dispatch_tool()`)
     c. Execute on the `FileEditor` — this is where the actual edit happens in Python
     d. Record the change in `ChangeReport` (capturing real before/after from the file)
     e. If the tool call failed (bad regex, wrong line number, content mismatch), increment an error counter. If 3 consecutive errors → bail out early
     f. Build a `FunctionResponse` with the result + the updated file state (numbered lines)
     g. Append Gemini's message and our response to conversation history
     h. Go back to step 1
   - If Gemini returned **only text** (e.g., "DONE: replaced X with Y") → the agent considers itself finished. Exit the loop.

3. **Return** an `EditResult` with the final file content and the change report.

### Key Safety Mechanisms

- **Content verification:** `replace_line` and `delete_line` require `expected_content` — the FileEditor checks that the line actually contains what the agent thinks before editing
- **Consecutive error cap (3):** Prevents infinite retry loops when the LLM keeps producing bad tool calls
- **Total turn cap (20):** Prevents runaway agent loops regardless of error count
- **Updated file state after every edit:** The LLM always sees current line numbers, not stale ones from before previous edits shifted things around

## How This Differs From the Surgical JSON Repair Prototype

| Surgical JSON Repair Prototype | Agent Editing Framework |
|---|---|
| Specific to JSON learning modules | Works on any plain-text file |
| Structured ErrorReport input (block_id, field_path, error_type) | One generic natural language instruction |
| Field-level patching via Pydantic models | Line-by-line edits using regex |
| Anthropic/Claude only | Must support Gemini at minimum |
| Synchronous | Must be async |
| Outputs patched module in memory | Outputs edited file + JSON change report |
| Integrated into test scripts | Standalone Python package |

## What Carries Over From the Prototype

- The core insight that the LLM should only generate targeted fixes, not regenerate entire files
- Understanding of how to prompt an LLM for precise, scoped edits
- The idea of validating results after patching
- Experience with structuring repair/edit pipelines

## Feasibility Assessment

This is feasible. The concept is essentially what tools like Claude Code do — receive a natural language instruction, read a file, and make targeted edits. The same idea, packaged as a library.
The flow would be something like:
1. LLM reads the file + instruction
2. LLM decides: "I need to replace X with Y on lines matching this pattern"
3. LLM calls a regex tool to find those lines
4. Python executes the replacement deterministically
5. The before/after is captured from the actual text (not LLM-generated)

**Regex as a tool:** The LLM agent generates regex patterns as part of its reasoning to locate relevant lines (e.g., "find all lines matching `"oxygen": \d+`"). Python's `re` module executes the actual find-and-replace deterministically. The LLM decides *what* to search for and *what* to replace it with; Python does the mechanical work.

**No single component is complex on its own.** Regex matching, file reading, line-level editing, change tracking — all straightforward Python. The main engineering challenges are:
- Designing the agent loop cleanly (how the LLM reasons, calls tools, and iterates)
- Making it properly async
- Working with the Gemini SDK (different from Anthropic's)
- Package structure and clean API design

## Open Questions

- Should other LLM providers (Anthropic, OpenAI) also be supported, or is Gemini the only requirement?
- What are the expected file sizes? This affects how much context the LLM needs
- Should the agent handle multi-step edits where later edits depend on earlier ones (line numbers shift after insertions/deletions)?
- What error handling is expected when the LLM produces an invalid regex or targets a non-existent line?
- What does "async in nature" mean specifically — async API calls, async file I/O, or the package exposing an async interface to callers?
- ~~What exactly does Thinglink's system pass as `instructions`and `content`?~~ **RESOLVED (2026-03-24, confirmed by Saif):** Approach 1 — instructions will be literal and specific. Thinglink's upstream agents figure out *what* needs fixing; our tool just locates and executes the edit. Our LLM agent does not need to analyze the file for errors or reason about correctness — it receives clear instructions like "replace X with Y". This keeps context window usage low and the agent loop simple. Note: the agent still needs *some* intelligence (e.g., generating regex patterns, handling multiple matches across the file), but it does not need to understand the content semantically.

## Preliminary answers to open questions (need to be checked with Saif)
- Other LLM providers can probably be supported, let's start with Gemini though since Thinglink mainly uses that for the API connections.
- Expected file sizes are small to medium at the start, the prototype should start with the focus on working with files and file sizes that are reasonable. If indeed Thinglink does need this tool for files that are tens of thousands of lines (and 10x more tokens), we need to implement some large-file handling logic, but only later if that is indeed necessary. Could be that we only just work with files that are 500 lines max, for example.
- Multi-step issue: This could be solved with just that the agent only works with the updated file content, not the original, after each edit operation. So if it edits something in step 1, the agent should just see the new file state before deciding what to do for step 2, and so on. Maybe unnecessary if multi-step tool calls are not used by Thinglink, but a nice-to-have feature still.
- Error handling: if the LLM generates invalid regex, use Python's `re-compile()`that throws a `re.error` on any invalid patterns. Then tell the agent "that regex was invalid, here's the error", and retry. The agent loop (should) already support retries by nature, so this is just another iteration. For non-existent lines, this could only happen if the agent completely hallucinates a line number instead of using what the regex tool returns. But this should be fized with just validating somehow that any line number the agent references actually exists in the current file before executing, and maybe that the contents match as to what is expected. So both cases of error handling kind of fall into the same handling: validate before executing, and if something's wrong, tell the agent and let it retry. Something like:
Agent sends edit request
-> Is the line number valid? If no -> "Line X doesn't exist, file has Y lines"
-> Is the regex valid? If no -> "invalid pattern: [error_message]"
-> Did the regex match anything? If no -> "No matches found, try a different pattern"
-> If everything good -> execute the edit
** Should we verify the contents of a code line as well as the fact that the code line exists? **
Example scenario:
-> Regex tool finds `"tool_count": 21` on line 17. The agent decides to replace it with something. But between the search and the edit, a previous edit in the same call shifted the lines. Now line 17 contains something completely different. The agent says "replace line 17 with `"tool_count": 17` and Python blindly overwrites whatever there is now. 
-> The simplest way to check this: when the agent requests an edit, it provides both the line number and the expected content of that line (or at least a substring). Python then checks that line 18 actually contains what the agent thinks it contains before executing.
So the flow for changing a line is essentially this:
1. The LLM says: "REPLACE line 17 with `"tool_count: 17"`
2. Before executing, Python reads what line 17 actually contains (like `"tool_count: 21"`) and saves that as `before`
3. Python performs the replacement action
4. Python reads the line again and saves the actual result as `after`
So the before/after in the change report are snapshots from the real file, not what the LLM thinks was there. The LLM only decides what to do (the instruction), but Python captures what actually happened (the record).
