"""FixPilot AI Jest output parser.

Responsibilities:
- Parse Jest output and extract failure information.
- Handle both the default reporter output and the ``--verbose`` reporter.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
from typing import List, Optional

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


# Test file extensions Jest may report (js, jsx, ts, tsx, mjs, cjs).
_TEST_FILE_RE = r"[^\s]*\.(?:js|jsx|ts|tsx|mjs|cjs)"

# "  ✕ test description (2 ms)" - unicode and ASCII markers.
_FAILING_TEST_RE = re.compile(r"^\s*[\u2715\u00d7xX]\s+(.+?)\s+\([\d.]+\s*m?s\)")

# "  ● Test description" or "  * Test description"
_BULLET_RE = re.compile(r"^\s*[\u25cf*]\s+(.+)$")

# "    at Object.<anonymous> (src/file.js:18:24)"
_STACK_WITH_PAREN_RE = re.compile(r"^\s+at\s+(.+?)\s+\((.+):(\d+):(\d+)\)")

# "    at src/file.js:18:24"
_STACK_SIMPLE_RE = re.compile(r"^\s+at\s+(.+):(\d+):(\d+)")


class JestParser(DiagnosticParser):
    """Parser for Jest output."""

    def __init__(self, language: str = "javascript"):
        self._language = language

    @property
    def language(self) -> str:
        return self._language

    @property
    def test_framework(self) -> str:
        return "jest"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse Jest output and extract failure information.

        Two reporter styles are supported:

        * default reporter - a ``●`` bullet introduces each failure and the
          bullet text is the failing test name.
        * ``--verbose`` reporter - a ``✕`` marker names the failing test and a
          following ``●`` bullet introduces its error detail.
        """
        failures: List[DiagnosticEvidence] = []
        full_output = (output or "") + "\n" + (stderr or "")

        current_test: Optional[str] = None
        current_error_lines: List[str] = []
        current_traceback: List[dict] = []
        current_file_refs: List[str] = []
        current_suite: Optional[str] = None
        in_error_block = False

        def flush() -> None:
            nonlocal current_test, current_error_lines, current_traceback
            nonlocal current_file_refs, in_error_block
            if current_test is not None:
                error = "\n".join(current_error_lines).strip()
                failures.append(
                    self._build_evidence(
                        current_test,
                        error or f"Test '{current_test}' failed",
                        current_traceback,
                        current_file_refs,
                    )
                )
            current_test = None
            current_error_lines = []
            current_traceback = []
            current_file_refs = []
            in_error_block = False

        for line in full_output.split("\n"):
            # "FAIL ./src/test.js" - failing suite
            suite_fail = re.match(rf"^\s*FAIL\s+({_TEST_FILE_RE})", line)
            if suite_fail:
                flush()
                current_suite = suite_fail.group(1).strip()
                continue

            # "PASS ./src/test.js" - successful suite
            suite_pass = re.match(rf"^\s*PASS\s+({_TEST_FILE_RE})", line)
            if suite_pass:
                continue

            # "  ✕ test description (2 ms)" - failing test (verbose reporter)
            test_fail = _FAILING_TEST_RE.match(line)
            if test_fail:
                flush()
                test_name = test_fail.group(1).strip()
                current_test = f"{current_suite} > {test_name}" if current_suite else test_name
                current_error_lines = []
                current_traceback = []
                current_file_refs = []
                in_error_block = False
                continue

            # "  ● Test description" - failure bullet / error detail header
            bullet_match = _BULLET_RE.match(line)
            if bullet_match:
                name = bullet_match.group(1).strip()
                if current_test is None:
                    # Default reporter: the bullet *is* the failing test.
                    current_test = name
                    current_error_lines = []
                    current_traceback = []
                    current_file_refs = []
                    in_error_block = True
                elif not current_error_lines:
                    # Verbose reporter: detail header for the known test.
                    # The bullet text carries the fuller "Suite > test" name.
                    current_test = name
                    in_error_block = True
                else:
                    # A previous failure already has content - start a new one.
                    flush()
                    current_test = name
                    current_error_lines = []
                    current_traceback = []
                    current_file_refs = []
                    in_error_block = True
                continue

            # Stack trace frames
            stack_match = _STACK_WITH_PAREN_RE.match(line)
            if stack_match:
                file_path = stack_match.group(2)
                current_traceback.append({
                    "file": file_path,
                    "line": int(stack_match.group(3)),
                    "function": stack_match.group(1),
                })
                if file_path not in current_file_refs:
                    current_file_refs.append(file_path)
                continue

            simple_stack = _STACK_SIMPLE_RE.match(line)
            if simple_stack:
                file_path = simple_stack.group(1)
                current_traceback.append({
                    "file": file_path,
                    "line": int(simple_stack.group(2)),
                    "function": "anonymous",
                })
                if file_path not in current_file_refs:
                    current_file_refs.append(file_path)
                continue

            # Everything else inside an error block is error detail.
            if current_test is not None and in_error_block:
                # Stop at the reporter's summary block.
                if re.match(r"^\s*(Test Suites|Tests|Snapshots|Time|Ran all test suites)\b", line):
                    in_error_block = False
                    continue
                stripped = line.strip()
                if stripped:
                    current_error_lines.append(stripped)
                elif current_error_lines:
                    current_error_lines.append("")

        # Don't forget the last failure
        flush()

        return failures

    def _build_evidence(
        self, test_name: str, error: str, traceback_frames: list, file_refs: list
    ) -> DiagnosticEvidence:
        """Build DiagnosticEvidence from parsed data."""
        exception_type = "AssertionError"
        exception_message = error

        # Try to extract exception type from error
        for known in (
            "TypeError",
            "ReferenceError",
            "SyntaxError",
            "RangeError",
            "AssertionError",
        ):
            if known in error:
                exception_type = known
                break

        # "TypeError: message" -> use the message part only.
        first_line = error.split("\n")[0] if error else ""
        match = re.match(r"^([A-Za-z]*Error|AssertionError)\s*:\s*(.+)$", first_line)
        if match:
            exception_type = match.group(1)
            exception_message = match.group(2).strip() or error
        else:
            exception_message = error.strip()

        traceback_str = (
            "\n".join(
                f'File "{f["file"]}", line {f["line"]}, in {f["function"]}'
                for f in traceback_frames
            )
            if traceback_frames
            else "No traceback available"
        )

        line_range = (0, 0)
        if traceback_frames:
            line_range = (traceback_frames[0]["line"], traceback_frames[-1]["line"])

        return DiagnosticEvidence(
            summary=f"Test '{test_name}' failed",
            exception_type=exception_type,
            exception_message=exception_message,
            failing_test=test_name,
            traceback=traceback_str,
            file_references=file_refs[:5],
            line_range=line_range,
            snippet="",
            redacting=False,
            language=self._language,
            test_framework="jest",
        )


# Register the parser for JavaScript and TypeScript.
PARSER_REGISTRY.register(JestParser("javascript"))
PARSER_REGISTRY.register(JestParser("typescript"))
