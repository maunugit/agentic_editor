"""Regex search, bounded file reads, and deterministic edit operations."""

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


@dataclass
class LineSnapshot:
    """A single line read from the current file state."""

    line_number: int
    content: str


@dataclass
class RegexSearchResult:
    """A bounded regex search result with compact metadata."""

    matches: list[RegexMatch]
    total_matches: int
    truncated: bool


class FileEditor:
    """Manages file content as lines and provides edit operations.

    All line numbers are 1-based to match what the LLM sees.
    After each edit, the internal state is updated so subsequent operations
    work against the current file state, not the original.
    """

    MAX_GET_LINES_RANGE = 20
    DEFAULT_MAX_SEARCH_RESULTS = 20
    DEFAULT_LINE_PREVIEW_CHARS = 200

    def __init__(self, content: str) -> None:
        self._lines = content.split("\n")

    @property
    def content(self) -> str:
        return "\n".join(self._lines)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def get_line(self, line_number: int) -> str:
        """Get the content of a specific line (1-based)."""
        self._validate_line_number(line_number)
        return self._lines[line_number - 1]

    def get_lines(self, start_line: int, end_line: int) -> list[LineSnapshot]:
        """Get a bounded range of lines from the current file state."""
        self._validate_line_range(start_line, end_line)
        if end_line - start_line + 1 > self.MAX_GET_LINES_RANGE:
            raise LineRangeTooLargeError(
                start_line,
                end_line,
                self.MAX_GET_LINES_RANGE,
            )
        return [
            LineSnapshot(line_number=i, content=self._lines[i - 1])
            for i in range(start_line, end_line + 1)
        ]

    def regex_search(
        self,
        pattern: str,
        *,
        max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
        preview_chars: int = DEFAULT_LINE_PREVIEW_CHARS,
    ) -> RegexSearchResult:
        """Search all lines for a regex pattern.

        Args:
            pattern: A regular expression pattern to search for.
            max_results: Maximum number of matches to return.
            preview_chars: Maximum number of characters to include in each line preview.

        Returns:
            A bounded RegexSearchResult with compact metadata.

        Raises:
            re.error: If the pattern is not valid regex.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        if preview_chars < 1:
            raise ValueError("preview_chars must be at least 1")

        compiled = re.compile(pattern)
        matches: list[RegexMatch] = []
        total_matches = 0

        for i, line in enumerate(self._lines, start=1):
            match = compiled.search(line)
            if not match:
                continue

            total_matches += 1
            if len(matches) >= max_results:
                continue

            matches.append(
                RegexMatch(
                    line_number=i,
                    line_content=self._truncate_preview(line, preview_chars),
                    match_text=match.group(),
                )
            )

        return RegexSearchResult(
            matches=matches,
            total_matches=total_matches,
            truncated=total_matches > len(matches),
        )

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
        if line_number < 1 or line_number > self.line_count:
            raise LineNumberError(line_number, self.line_count)

    def _validate_line_range(self, start_line: int, end_line: int) -> None:
        if start_line < 1 or start_line > self.line_count:
            raise LineNumberError(start_line, self.line_count)
        if end_line < 1 or end_line > self.line_count:
            raise LineNumberError(end_line, self.line_count)
        if end_line < start_line:
            raise InvalidLineRangeError(start_line, end_line)

    def _verify_content(self, line_number: int, expected_content: str | None) -> None:
        if expected_content is None:
            return
        actual = self._lines[line_number - 1]
        if actual != expected_content:
            raise ContentMismatchError(line_number, expected_content, actual)

    @staticmethod
    def _truncate_preview(line: str, preview_chars: int) -> str:
        if len(line) <= preview_chars:
            return line
        if preview_chars <= 3:
            return line[:preview_chars]
        return f"{line[: preview_chars - 3]}..."


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


class InvalidLineRangeError(Exception):
    """Raised when a requested line range is structurally invalid."""

    def __init__(self, start_line: int, end_line: int) -> None:
        self.start_line = start_line
        self.end_line = end_line
        super().__init__(
            f"Invalid line range: start_line {start_line} must be <= end_line {end_line}"
        )


class LineRangeTooLargeError(Exception):
    """Raised when a requested line range exceeds the configured limit."""

    def __init__(self, start_line: int, end_line: int, max_range: int) -> None:
        self.start_line = start_line
        self.end_line = end_line
        self.max_range = max_range
        super().__init__(
            f"Requested line range {start_line}-{end_line} exceeds the maximum "
            f"allowed range of {max_range} lines"
        )
