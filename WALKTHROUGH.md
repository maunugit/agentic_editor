## Walkthrough of the flow

# Thinglink calls the tool
1. Thinglink's code calls it with `from agentic_editor import edit_file` 
2. __init__.py handles it, calls `edit_file()`
3. `edit_file()` validates inputs (empty instruction? empty content?)
    If valid, calls `run_agent()`
4. agent.py -> `run_agent()` 
    -> Creates the Gemini client
    -> Creates a FileEditor (from `tools.py`) with the file content
    -> Creates a ChangeReport (from `models.py`) to record edits
    -> Runs the agent loop (calls Gemini, dispatches tools, repeats)
    -> Returns EditResult (from `models.py`) with final content + report
5. During the loop, uses:
    -> `tools.py`:
        FileEditor:
        -> regex_search(): find lines matching a pattern
        -> replace(): swap a line's content
        -> add(): insert a new line
        -> Holds the mutable file state as a list of lines
        -> Enforce safety (line number bounds, verifying content)
    -> `models.py` (data containers):
        -> ChangeEntry: onre recorded edit (line, operation, before, after)
        -> ChangeReport: list of ChangeEntry objects
        -> EditResult: final output (edited content + report)
        -> OperationType: enum (REPLACE, DELETE, ADD)
6. Back to Thinglink: 
    -> result.content (the edited file as a string)
    -> result.report (the structured change report (or None))

`models.py` and `tools.py` know nothing about Gemini, they're just pure Python. Data containers and file operations. `agent.py` is the only file that talks to the API and orchestrates eberything. `init.py` is the entry point.


## Agentic cloop with a concrete example (bit simplified, from demo)
Let's say Thinglink's evaluator found two issues in a generated block: 

  await edit_file(
      instruction='1. "93 billion miles" is wrong, should be "93 million miles"\n'
                  '2. "terrestial" is a typo, fix to "terrestrial"',
      content="The Sun is approximately 93 billion miles from Earth.\n"
              "The inner planets are known as terrestial planets.",
  )
# Turn 1
`run_agent()` sends a SYSTEM_INSTRUCTIONS to Gemini and the user message: 
    1. "93 billion miles" is wrong...
    File content:
    1. The Sun is approximately 93 billion miles from Earth.
    2. The inner planets are known as terrestial planets.

Gemini responds wtih a function call (not free-form text):
`regex_search(pattern="93 billion")`

The tool executes it on `FileEditor.regex_search("93 billion")` and returns a match at line 1.
We send back:
    FunctionResponse: {status: "success", matches: [{line_number: 1,
    line_content: "The Sun is...", match_text: "93 billion"}]}
    Updated file state:
    1: The Sun is approximately 93 billion miles from Earth.
    2: The inner planets are known as terrestial planets.
# Turn 2
Gemini now knows where the target is, now performs the edit
The API responds:
  replace_line(line_number=1, new_content="The Sun is approximately 93 million miles from Earth.", expected_content="The Sun is approximately 93 billion miles from Earth.")

  We execute it:
  1. FileEditor._validate_line_number(1) —> line 1 exists, OK
  2. FileEditor._verify_content(1, "The Sun is approximately 93 billion...") —> matches actual content, OK
  3. FileEditor.replace(1, "The Sun is approximately 93 million...") —> swaps the line in self._lines
  4. ChangeReport.add_change(ChangeEntry(line_numbers=[1], operation=REPLACE,
   before="...93 billion...", after="...93 million...")) —> recorded

Tool sends back the result + updated file state (line 1 now shows "93 million")

# Turn 3
Gemini moves to second issue, fixes the "terrestial" word similarly

# Turn 4 
Now everything's done, Gemini responds with text only:
"DONE: Fixed this and that on lines X and Y..."
`_has_function_calls()` returns False so we break out of the loop, returns the `EditResult`

The returned info goes back through __init__.py and back to Thinglink's system.

The pattern is search -> edit -> search -> edit -> DONE. Gemini always searches line numbers and between every turn the conversatino history is appended so it remembers what has happened.

The key thing is that with `TOOL_DECLARATIONS` in the FunctionDeclaration and the ContentConfig we set for the SDK, Gemini can only respond in two ways:
1. A function call (like, function_call.name = "regex_search")
2. A text part (like, "DONE: fixed typos...")

It can only do free-form text when it's done. The `has_function_calls()` checks this. If Gemini breaks the rules and starts to ramble about something the loop breaks. Similarly, like it should do, if it responds with "DONE: here's what I did..." the loop breaks. But if it's an actual function call based on the tool schema, we use the dispatch tool to actually use the function. 

The function calling is a structured API feature. We don't need to parse it or hope it formatted things correctly and so on. The reasoning as to why it decided to do something is unknown, it's somewhere in Google's servers. The SDK essentially forces Gemini into a constrained output mode when tools are provided, but it's not full constrained decoding like with a grammar. But the API guarantees that function calls come back in the correct schema format.