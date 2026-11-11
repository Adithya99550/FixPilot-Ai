"""FixPilot AI Go test output parser.

Responsibilities:
- Parse Go test output and extract failure information.
- Handle the ``t.Errorf`` / ``t.Fatal`` style (diagnostic line before the
  ``--- FAIL:`` summary line) as well as panic failures.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
from typing import List, Tuple

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


# "--- FAIL: TestName (0.00s)" - may be indented for subtests.
_FAIL_RE = re.compile(r"^\s*---\s+FAIL:\s+(\S+)(?:\s+\([\d.]+s\))?\s*$")

# "--- PASS: TestName (0.00s)"
_PASS_RE = re.compile(r"^\s*---\s+(?:PASS|SKIP):\s+(\S+)")

# "    calc_test.go:12: got -1, want 5"
_ERROR_RE = re.compile(r"^\s*([\w./\\-]+\.go):(\d+):\s*(.+)$")

# "=== RUN   TestName"
_RUN_RE = re.compile(r"^\s*===\s+RUN\s+(\S+)")

# "panic: runtime error: index out of range [3] with length 2"
_PANIC_RE = re.compile(r"^\s*panic:\s*(.+)$")


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
        failures: List[DiagnosticEvidence] = []
        full_output = (output or "") + "\n" + (stderr or "")

        # Failing test names in order of appearance.
        fail_names: List[str] = []
        # Buffered (file, line, message) diagnostics not yet attached.
        pending_errors: List[Tuple[str, int, str]] = []
        # Diagnostics attached per failing test name.
        attached: dict = {}

        for raw_line in full_output.split("\n"):
            line = raw_line.rstrip()

            fail_match = _FAIL_RE.match(line)
            if fail_match:
                name = fail_match.group(1)
                if name not in fail_names:
                    fail_names.append(name)
                # Diagnostics printed just before the FAIL line belong to it.
                if pending_errors and name not in attached:
                    attached[name] = list(pending_errors)
                    pending_errors = []
                continue

            if _PASS_RE.match(line):
                continue

            run_match = _RUN_RE.match(line)
            if run_match:
                continue

            error_match = _ERROR_RE.match(line)
            if error_match:
                pending_errors.append((
                    error_match.group(1),
                    int(error_match.group(2)),
                    error_match.group(3).strip(),
                ))
                continue

            panic_match = _PANIC_RE.match(line)
            if panic_match:
                pending_errors.append(("", 0, "panic: " + panic_match.group(1).strip()))
                continue

        # Any diagnostics left over belong to the first failing test.
        if pending_errors and fail_names:
            attached.setdefault(fail_names[0], []).extend(pending_errors)

        # Subtests that carry no diagnostic of their own inherit from the
        # parent test (e.g. "TestAdd/positive" inherits from "TestAdd").
        for name in fail_names:
            if name in attached:
                continue
            parts = name.split("/")
            for i in range(len(parts) - 1, 0, -1):
                parent = "/".join(parts[:i])
                if parent in attached:
                    attached[name] = attached[parent]
                    break

        for name in fail_names:
            errors = attached.get(name, [])
            failures.append(self._build_evidence(name, errors))

        return failures

    def _build_evidence(self, test_name: str, errors: List[Tuple[str, int, str]]):
        """Build DiagnosticEvidence from parsed data."""
        messages = [msg for (_f, _l, msg) in errors if msg]
        error_text = "\n".join(messages)

        file_path = ""
        line_num = 0
        for f, l, _msg in errors:
            if f:
                file_path = f
                line_num = l
                break

        exception_type = "AssertionError"
        lowered = error_text.lower()
        if "panic:" in lowered:
            exception_type = "Panic"
        elif "undefined:" in lowered or "cannot use" in lowered or "build failed" in lowered:
            exception_type = "CompileError"
        elif "expected" in lowered or "got " in lowered:
            exception_type = "AssertionError"

        if not error_text:
            error_text = f"Test '{test_name}' failed"

        traceback_parts = []
        for f, l, msg in errors:
            if f:
                traceback_parts.append(f'File "{f}", line {l}: {msg}')
            else:
                traceback_parts.append(msg)
        traceback_str = "\n".join(traceback_parts) if traceback_parts else "No traceback available"

        line_range = (line_num, line_num) if line_num > 0 else (0, 0)
        file_refs = [file_path] if file_path else []

        return DiagnosticEvidence(
            summary=f"Test '{test_name}' failed",
            exception_type=exception_type,
            exception_message=error_text,
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
