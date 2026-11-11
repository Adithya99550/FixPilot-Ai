"""FixPilot AI Go test output parser.

Responsibilities:
- Parse Go test output and extract failure information.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
from typing import List

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


class GoTestParser(DiagnosticParser):
    """Parser for Go test output."""

    @property
    def language(self) -> str:
        return "go"

    @property
    def test_framework(self) -> str:
        return "go test"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse Go test output and extract failure information."""
        failures = []
        full_output = output + "\n" + stderr

        # Go test output patterns:
        # --- FAIL: TestName (0.00s)
        #     file_test.go:10: error message
        # FAIL
        # --- PASS: TestName (0.00s)

        lines = full_output.split("\n")
        current_test = None
        current_error = ""
        current_file = ""
        current_line = 0

        for line in lines:
            # Match "--- FAIL: TestName (0.00s)"
            fail_match = re.match(r"^--- FAIL:\s+(\w+)\s+\([\d.]+s\)", line)
            if fail_match:
                # Save previous test if any
                if current_test and current_error:
                    failures.append(self._build_evidence(
                        current_test, current_error, current_file, current_line
                    ))
                current_test = fail_match.group(1)
                current_error = ""
                current_file = ""
                current_line = 0
                continue

            # Match "file_test.go:10: error message"
            error_match = re.match(r"^(\S+_test\.go):(\d+):\s*(.+)$", line.strip())
            if error_match and current_test:
                current_file = error_match.group(1)
                current_line = int(error_match.group(2))
                current_error += "\n" + error_match.group(3) if current_error else error_match.group(3)
                continue

            # Match panic stack traces
            if current_test and "panic:" in line:
                current_error += "\n" + line.strip()
                continue

            # Match goroutine stack traces
            if current_test and (line.strip().startswith("goroutine") or "runtime/debug.Stack()" in line):
                current_error += "\n" + line.strip()
                continue

        # Don't forget the last test
        if current_test and current_error:
            failures.append(self._build_evidence(
                current_test, current_error, current_file, current_line
            ))

        return failures

    def _build_evidence(self, test_name: str, error: str, file_path: str, line_num: int):
        """Build DiagnosticEvidence from parsed data."""
        exception_type = "TestingError"
        exception_message = error

        traceback_str = f'File "{file_path}", line {line_num}' if file_path else "No traceback available"
        line_range = (line_num, line_num) if line_num > 0 else (0, 0)
        file_refs = [file_path] if file_path else []

        return DiagnosticEvidence(
            summary=f"Test '{test_name}' failed",
            exception_type=exception_type,
            exception_message=exception_message,
            failing_test=test_name,
            traceback=traceback_str,
            file_references=file_refs,
            line_range=line_range,
            snippet="",
            redacting=False,
            language="go",
            test_framework="go test",
        )


# Register the parser
PARSER_REGISTRY.register(GoTestParser())