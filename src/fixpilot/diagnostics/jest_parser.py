"""FixPilot AI Jest output parser.

Responsibilities:
- Parse Jest output and extract failure information.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
from typing import List

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


class JestParser(DiagnosticParser):
    """Parser for Jest output."""

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def test_framework(self) -> str:
        return "jest"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse Jest output and extract failure information."""
        failures = []
        full_output = output + "\n" + stderr

        # Jest output patterns:
        # FAIL ./path/to/test.js
        #   ✕ test description (time)
        #   ● Test description
        #   Expected: ...
        #   Received: ...
        #   at file:line:col
        #   at Object.<anonymous> (file:line:col)

        lines = full_output.split("\n")
        current_test = None
        current_error = None
        current_traceback = []
        current_file_refs = []
        current_suite = None

        for i, line in enumerate(lines):
            # Match "FAIL ./test_file.js" - test suite (file path only)
            suite_fail = re.match(r"^\s*FAIL\s+(.+?\.js)\b", line)
            if suite_fail:
                current_suite = suite_fail.group(1).strip()
                continue

            # Match "  ✕ test description (time)" - individual failing test
            # Jest times can be "(2 ms)", "(2s)", "(2.5s)" or "(7.86 s)"
            # Support both unicode (✕ ×) and ASCII (x X) markers
            test_fail = re.match(r"^\s*[✕×xX]\s+(.+?)\s+\([\d.]+\s*m?s\)", line)
            if test_fail:
                # Save previous test if any
                if current_test and current_error:
                    failures.append(self._build_evidence(
                        current_test, current_error, current_traceback, current_file_refs
                    ))
                test_name = test_fail.group(1).strip()
                # Prefix with suite name if available
                if current_suite:
                    current_test = f"{current_suite} › {test_name}"
                else:
                    current_test = test_name
                current_error = ""
                current_traceback = []
                current_file_refs = []
                continue

            # Match test description with bullet: "  ● Test description" or "  * Test description"
            bullet_match = re.match(r"^\s*[●\*]\s+(.+)$", line)
            if bullet_match and current_test:
                current_error = bullet_match.group(1).strip()
                continue

            # Match "Expected:" / "Received:" lines
            if current_test and (line.strip().startswith("Expected:") or line.strip().startswith("Received:")):
                current_error += "\n" + line.strip()
                continue

            # Match stack trace lines: "    at file:line:col"
            # or "    at Object.<anonymous> (file:line:col)"
            stack_match = re.match(r"^\s+at\s+(.+?)\s+\((.+):(\d+):(\d+)\)", line)
            if stack_match and current_test:
                file_path = stack_match.group(2)
                line_num = int(stack_match.group(3))
                current_traceback.append({
                    "file": file_path,
                    "line": line_num,
                    "function": stack_match.group(1),
                })
                if file_path not in current_file_refs:
                    current_file_refs.append(file_path)
                continue

            # Match simpler stack trace: "    at file:line:col"
            simple_stack = re.match(r"^\s+at\s+(.+):(\d+):(\d+)", line)
            if simple_stack and current_test:
                file_path = simple_stack.group(1)
                line_num = int(simple_stack.group(2))
                current_traceback.append({
                    "file": file_path,
                    "line": line_num,
                    "function": "anonymous",
                })
                if file_path not in current_file_refs:
                    current_file_refs.append(file_path)
                continue

        # Don't forget the last test
        if current_test and current_error:
            failures.append(self._build_evidence(
                current_test, current_error, current_traceback, current_file_refs
            ))

        return failures

    def _build_evidence(self, test_name: str, error: str, traceback_frames: list, file_refs: list):
        """Build DiagnosticEvidence from parsed data."""
        exception_type = "AssertionError"
        exception_message = error

        # Try to extract exception type from error
        if "TypeError" in error:
            exception_type = "TypeError"
        elif "ReferenceError" in error:
            exception_type = "ReferenceError"
        elif "SyntaxError" in error:
            exception_type = "SyntaxError"

        traceback_str = "\n".join(
            f'File "{f["file"]}", line {f["line"]}, in {f["function"]}'
            for f in traceback_frames
        ) if traceback_frames else "No traceback available"

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
            language="javascript",
            test_framework="jest",
        )


# Register the parser
PARSER_REGISTRY.register(JestParser())