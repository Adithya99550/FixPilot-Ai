"""FixPilot AI Cargo test output parser.

Responsibilities:
- Parse Cargo test output and extract failure information.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
from typing import List

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


class CargoTestParser(DiagnosticParser):
    """Parser for Cargo test output."""

    @property
    def language(self) -> str:
        return "rust"

    @property
    def test_framework(self) -> str:
        return "cargo test"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse Cargo test output and extract failure information."""
        failures = []
        full_output = output + "\n" + stderr

        # Cargo test output patterns:
        # test test_name ... FAILED
        #   ---
        #   thread 'test_name' panicked at 'error message', file.rs:10:5
        #   ...
        # failures:
        #     test_name

        lines = full_output.split("\n")
        current_test = None
        current_error = ""
        current_file = ""
        current_line = 0
        in_failure = False
        in_failures_section = False
        listed_failures = []

        for line in lines:
            # Match "test test_name ... FAILED"
            fail_match = re.match(r"^test\s+(\S+)\s+\.\.\.\s+FAILED", line)
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
                in_failure = True
                in_failures_section = False
                continue

            # Match "test test_name ... ok"
            ok_match = re.match(r"^test\s+(\S+)\s+\.\.\.\s+ok", line)
            if ok_match and current_test == ok_match.group(1):
                # This test passed, discard current failure
                current_test = None
                current_error = ""
                in_failure = False
                continue

            # The "failures:" section lists the names of the failed tests
            # (one per line, indented). It is the fallback when the panic
            # message was truncated.
            if line.strip() == "failures:":
                in_failures_section = True
                continue
            if in_failures_section:
                stripped = line.strip()
                if not stripped:
                    in_failures_section = False
                    continue
                if stripped.startswith("test result:"):
                    in_failures_section = False
                    continue
                if stripped not in listed_failures:
                    listed_failures.append(stripped)
                continue

            # Match panic location: "thread 'test_name' panicked at src/lib.rs:43:9:"
            # or "thread 'test_name' panicked at 'message', file.rs:10:5"
            # The path group must be non-greedy/restricted so that the
            # line number is not swallowed by the path.
            panic_match = re.search(
                r"panicked at\s+(?:'([^']+)',\s*)?([\w./\\-]+?):(\d+)(?::(\d+))?", line
            )
            if panic_match and current_test:
                msg = panic_match.group(1) or "panic"
                current_file = panic_match.group(2)
                current_line = int(panic_match.group(3))
                current_error = msg
                in_failure = True
                continue

            # Match assertion failure details (after the panic line)
            if in_failure and current_test and line.strip().startswith("assertion"):
                current_error += "\n" + line.strip()
                continue

            # Match multi-line error messages
            if in_failure and current_test and line.strip() and not line.startswith("test "):
                # Continuation of error message
                if "thread" not in line and "panicked" not in line:
                    current_error += "\n" + line.strip()

        # Don't forget the last test
        if current_test and current_error:
            failures.append(self._build_evidence(
                current_test, current_error, current_file, current_line
            ))
        elif current_test:
            # The test failed but no panic message was captured.
            failures.append(self._build_evidence(
                current_test, "test failed", current_file, current_line
            ))

        # Tests that are only listed in the "failures:" section.
        known = {failure.failing_test for failure in failures}
        for name in listed_failures:
            if name not in known:
                failures.append(self._build_evidence(name, "test failed", "", 0))

        return failures

    def _build_evidence(self, test_name: str, error: str, file_path: str, line_num: int):
        """Build DiagnosticEvidence from parsed data."""
        exception_type = "Panic"
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
            language="rust",
            test_framework="cargo test",
        )


# Register the parser
PARSER_REGISTRY.register(CargoTestParser())