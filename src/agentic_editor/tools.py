"""Regex tool and edit operations for the agentic editor.

The regex tool is supposed to be a search-only tool. 
The LLM generates patterns, Python executes them and returns matches with line numbers. 
Edit operations (replace, delete, add) are deterministic.
Python performs the edit and captures before/after from the actual file text.

This file defines the actual opreations. 
FileEditor class holds the file content and can modify it. AKA does the actual work:
Searching with regex, replacing lines, deleting lines, adding lines. Also enforces safety checks.
"""

import re
from dataclasses import dataclass


@dataclass
class RegexMatch:
    """A single regex match result.

    Attributes:
        line_number: 1-based line number where the match was found.
        line_content: The full text of the matching line.
        match_text: The specific substring that matched the pattern.
    """

    line_number: int
    line_content: str
    match_text: str


class FileEditor:
    """Manages file content as lines and provides edit operations.

    All line numbers are 1-based to match what the LLM sees.
    After each edit, the internal state is updated so subsequent operations
    work against the current file state, not the original.
    """

    def __init__(self, content: str) -> None:
        self._lines = content.split("\n") # split on \n gives a list where each element is one line

    @property # makes calling a method like calling a field. editor.content() VS editor.content
    def content(self) -> str:
        return "\n".join(self._lines) # if needed, content() gives the full file back again joined

    @property
    def line_count(self) -> int:
        return len(self._lines) # If a line is deleted, line_count automatically decreases on next check

    def get_line(self, line_number: int) -> str:
        """Get the content of a specific line (1-based)."""
        self._validate_line_number(line_number)
        return self._lines[line_number - 1] # "replace line 5" -> Python sees self._lines[4]

    def regex_search(self, pattern: str) -> list[RegexMatch]:
        """Search all lines for a regex pattern.

        Args:
            pattern: A regular expression pattern to search for.

        Returns:
            List of RegexMatch objects for each line that matched.

        Raises:
            re.error: If the pattern is not valid regex.
        """
        # Takes the pattern string from instructions, compliles it into regex object
        compiled = re.compile(pattern) 
        matches = []
        # Loops every line in the file, enumerate() gives both the index and the value
        # On each iteration, i is the line number and line is the text of that line
        for i, line in enumerate(self._lines, start=1): #start=1 makes the index 1-based
            # Tries to find the pattern somewhere in this line
            m = compiled.search(line) # search() looks for a match anywhere in the string
            if m: # match object found
                matches.append(RegexMatch( # Creates RegexMatch datalass with 3 fields
                    line_number=i, # which line matched
                    line_content=line, # full text of that line
                    match_text=m.group(), # the specific substring that regex matched
                ))
        return matches

    def replace(
        self, line_number: int, new_content: str, expected_content: str | None = None
    ) -> tuple[str, str]:
        """Replace the content of a line.

        Args:
            line_number: 1-based line number to replace.
            new_content: The new text for this line.
            expected_content: If provided within the agentic loop, the edit is rejected if the current
                line content doesn't match this string.

        Returns:
            A (before, after) tuple captured from the actual file text.

        Raises:
            LineNumberError: If line_number is out of range.
            ContentMismatchError: If expected_content doesn't match actual content.
        """
        self._validate_line_number(line_number)
        self._verify_content(line_number, expected_content)
        before = self._lines[line_number - 1]
        self._lines[line_number - 1] = new_content
        return before, new_content

    def delete(
        self, line_number: int, expected_content: str | None = None
    ) -> str:
        """Delete a line from the file.

        Args:
            line_number: 1-based line number to delete.
            expected_content: If provided, the edit is rejected if the current
                line content doesn't match.

        Returns:
            The content of the deleted line, captured from actual file text.

        Raises:
            LineNumberError: If line_number is out of range.
            ContentMismatchError: If expected_content doesn't match actual content.
        """
        self._validate_line_number(line_number)
        self._verify_content(line_number, expected_content)
        before = self._lines.pop(line_number - 1)
        return before

    def add(
        self, after_line: int, new_content: str
    ) -> None:
        """Add a new line after the specified line number.

        Use after_line=0 to insert at the very beginning of the file.

        Args:
            after_line: 1-based line number to insert after. Use 0 to insert
                before line 1.
            new_content: The text for the new line.

        Raises:
            LineNumberError: If after_line is out of range (< 0 or > line_count).
        """
        if after_line < 0 or after_line > self.line_count:
            raise LineNumberError(after_line, self.line_count)
        self._lines.insert(after_line, new_content)

    def _validate_line_number(self, line_number: int) -> None:
         # num is not less than 1 and not greater than total line count; within bounds
        if line_number < 1 or line_number > self.line_count:
            raise LineNumberError(line_number, self.line_count)

    def _verify_content(self, line_number: int, expected_content: str | None) -> None:
        if expected_content is None:
            return
        actual = self._lines[line_number - 1]
        if actual != expected_content:
            raise ContentMismatchError(line_number, expected_content, actual)


class LineNumberError(Exception):
    """Raised when a line number is out of range."""

    def __init__(self, line_number: int, total_lines: int) -> None:
        self.line_number = line_number
        self.total_lines = total_lines
        super().__init__(
            f"Line {line_number} is out of range (file has {total_lines} lines)"
        )


class ContentMismatchError(Exception):
    """Raised when line content doesn't match what the agent expects."""

    def __init__(self, line_number: int, expected: str, actual: str) -> None:
        self.line_number = line_number
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Line {line_number} content mismatch: "
            f"expected {expected!r}, got {actual!r}"
        )
