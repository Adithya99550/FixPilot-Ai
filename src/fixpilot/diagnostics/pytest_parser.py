"""FixPilot AI pytest output parser.

Responsibilities:
- Parse pytest output and Python tracebacks.
- Extract exception type, message, file, line, stack frames, failing test, and relevant snippets.
- Deduplicate repeated errors.
- Redact sensitive values.
- Produce structured diagnostic evidence.

The parser understands pytest's default reporter output:

* the ``FAILURES`` / ``ERRORS`` section, whose per-test blocks carry the
  ``E``-prefixed exception lines and the ``path/file.py:12: ExceptionType``
  trailer;
* the ``short test summary info`` section, whose ``FAILED path::test - msg``
  lines carry the canonical test node id.
"""

import re
from typing import List, Optional, Tuple

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


# "FAILED tests/test_calc.py::test_add - assert -1 == 5"
_SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$")

# "_______________________ test_add _______________________"
_BLOCK_RE = re.compile(r"^_{3,}\s*(.+?)\s*_{3,}$")

# "E       TypeError: cannot concatenate"
_E_LINE_RE = re.compile(
    r"^E\s+(?:(?P<etype>[\w.]*(?:Error|Exception|Failure|Warning))\s*:\s*)?(?P<msg>.*)$"
)

# "tests/test_calc.py:8: in test_add"
_FRAME_RE = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+):\s+in\s+(?P<func>.+)$")

# "tests/test_calc.py:8: TypeError"
_FILE_LINE_RE = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+):\s*(?P<rest>.*)$")

# "TypeError: cannot concatenate" (standalone, e.g. from a summary line)
_EXC_RE = re.compile(r"^(?P<etype>[\w.]*(?:Error|Exception|Failure))\s*:\s*(?P<msg>.*)$")


class PytestParser(DiagnosticParser):
    """Parser for pytest output."""

    @property
    def language(self) -> str:
        return "python"

    @property
    def test_framework(self) -> str:
        return "pytest"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse pytest output and extract failure information.

        Args:
            output: pytest stdout output
            stderr: pytest stderr output

        Returns:
            List of DiagnosticEvidence objects, one per failing test
        """
        full_output = (output or "") + "\n" + (stderr or "")

        blocks = _extract_failure_blocks(full_output)
        summaries = _extract_summary_entries(full_output)

        failures: List[DiagnosticEvidence] = []
        seen: set = set()

        # Preferred source of truth: the short test summary (canonical ids).
        for test_id, summary_message in summaries:
            if test_id in seen:
                continue
            seen.add(test_id)
            block_lines = _match_block(test_id, blocks)
            failures.append(
                _build_evidence(test_id, summary_message, block_lines)
            )

        # Fall back to the failure blocks when the summary is unavailable.
        if not failures:
            for name, block_lines in blocks:
                test_id = name
                if test_id in seen:
                    continue
                seen.add(test_id)
                failures.append(_build_evidence(test_id, None, block_lines))

        # Last resort: scan for test identifiers in the raw output.
        if not failures:
            for line in full_output.split("\n"):
                for match in re.findall(r"(test_\w+)", line):
                    if match in seen:
                        continue
                    seen.add(match)
                    failures.append(_build_evidence(match, None, None))
                    if len(failures) >= 10:
                        return failures

        return failures


def parse_pytest_output(output: str, stderr: str = "") -> List[DiagnosticEvidence]:
    """Parse pytest output and extract failure information (legacy function).

    Args:
        output: pytest stdout output
        stderr: pytest stderr output

    Returns:
        List of DiagnosticEvidence objects, one per failing test
    """
    parser = PytestParser()
    return parser.parse(output, stderr)


# ----------------------------------------------------------------------
# Extraction helpers
# ----------------------------------------------------------------------


def _extract_summary_entries(full_output: str) -> List[Tuple[str, Optional[str]]]:
    """Extract (test node id, message) pairs from the short test summary."""
    entries: List[Tuple[str, Optional[str]]] = []
    for line in full_output.split("\n"):
        stripped = line.strip()
        match = _SUMMARY_RE.match(stripped)
        if match:
            test_id = match.group(1).strip()
            message = match.group(2)
            if test_id:
                entries.append((test_id, message.strip() if message else None))
    return entries


def _extract_failure_blocks(full_output: str) -> List[Tuple[str, List[str]]]:
    """Split the FAILURES/ERRORS section into (name, lines) blocks."""
    blocks: List[Tuple[str, List[str]]] = []
    current_name: Optional[str] = None
    current_lines: List[str] = []
    in_section = False

    for line in full_output.split("\n"):
        stripped = line.strip()

        if re.match(r"^=+\s+(?:FAILURES|ERRORS)\s+=+$", stripped):
            in_section = True
            continue

        if in_section and "short test summary info" in stripped:
            break

        if not in_section:
            continue

        block_match = _BLOCK_RE.match(stripped)
        if block_match:
            if current_name is not None:
                blocks.append((current_name, current_lines))
            current_name = block_match.group(1).strip()
            current_lines = []
            continue

        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        blocks.append((current_name, current_lines))

    return blocks


def _match_block(test_id: str, blocks: List[Tuple[str, List[str]]]) -> Optional[List[str]]:
    """Find the failure block that belongs to a test node id."""
    if not blocks:
        return None

    tail = test_id.split("::")[-1]

    for name, block_lines in blocks:
        if name == tail:
            return block_lines

    for name, block_lines in blocks:
        if tail and (tail in name or name in tail):
            return block_lines

    return None


def _build_evidence(
    test_id: str,
    summary_message: Optional[str],
    block_lines: Optional[List[str]],
) -> DiagnosticEvidence:
    """Build DiagnosticEvidence from a summary entry and its failure block."""
    from fixpilot.diagnostics.redaction import redact_sensitive_data

    exception_type = ""
    exception_message = ""
    file_refs: List[str] = []
    frames: List[dict] = []
    snippet_lines: List[str] = []
    line_numbers: List[int] = []

    if block_lines:
        for raw in block_lines:
            stripped = raw.strip()

            # Failing source line: ">       result = add_numbers('a')"
            if stripped.startswith("> "):
                snippet_lines.append(stripped[2:].rstrip())
                continue

            # Frame line: "tests/test_calc.py:8: in test_type_error"
            frame_match = _FRAME_RE.match(stripped)
            if frame_match:
                path = frame_match.group("file")
                if path not in file_refs:
                    file_refs.append(path)
                line_numbers.append(int(frame_match.group("line")))
                frames.append({
                    "file": path,
                    "line": int(frame_match.group("line")),
                    "function": frame_match.group("func").strip(),
                })
                continue

            # Trailer: "tests/test_calc.py:8: TypeError"
            file_line_match = _FILE_LINE_RE.match(stripped)
            if file_line_match:
                path = file_line_match.group("file")
                if path not in file_refs:
                    file_refs.append(path)
                line_numbers.append(int(file_line_match.group("line")))
                rest = file_line_match.group("rest").strip()
                if rest and not exception_type and re.fullmatch(r"[\w.]+(Error|Exception)", rest):
                    exception_type = rest
                continue

            # Exception detail: "E       TypeError: cannot concatenate"
            e_match = _E_LINE_RE.match(raw)
            if e_match:
                etype = e_match.group("etype")
                message = e_match.group("msg").strip()
                if etype:
                    if not exception_type:
                        exception_type = etype
                    if message and not exception_message:
                        exception_message = message
                elif message and not exception_message:
                    exception_message = message
                continue

    # Fall back to the short-summary message for type/message.
    if summary_message:
        exc_match = _EXC_RE.match(summary_message.strip())
        if exc_match:
            if not exception_type:
                exception_type = exc_match.group("etype")
            if not exception_message:
                exception_message = exc_match.group("msg").strip()
        elif not exception_message:
            exception_message = summary_message.strip()

    if not exception_type:
        exception_type = "AssertionError" if exception_message else "UnknownError"

    snippet = "\n".join(snippet_lines)
    redacted_snippet = redact_sensitive_data(snippet) if snippet else ""
    redacted_message = redact_sensitive_data(exception_message) if exception_message else ""

    if line_numbers:
        line_range = (min(line_numbers), max(line_numbers))
    else:
        line_range = (0, 0)

    traceback_str = _build_traceback(frames) if frames else _build_summary_traceback(
        file_refs, line_numbers, exception_type, exception_message
    )

    return DiagnosticEvidence(
        summary=f"Test '{test_id}' failed",
        exception_type=exception_type,
        exception_message=redacted_message or "Test assertion failed",
        failing_test=test_id,
        traceback=traceback_str,
        file_references=file_refs[:5],
        line_range=line_range,
        snippet=redacted_snippet,
        redacting=bool(snippet or exception_message),
        language="python",
        test_framework="pytest",
    )


def _build_traceback(frames: List[dict]) -> str:
    """Build a traceback string from a frames list."""
    if not frames:
        return "No traceback available"

    parts = []
    for f in frames:
        parts.append(
            'File "' + f["file"] + '", line ' + str(f["line"]) + ', in ' + f["function"]
        )
    return "\n".join(parts)


def _build_summary_traceback(
    file_refs: List[str],
    line_numbers: List[int],
    exception_type: str,
    exception_message: str,
) -> str:
    """Build a traceback string when no explicit frames were available."""
    parts = []
    for path, number in zip(file_refs, line_numbers):
        parts.append('File "' + path + '", line ' + str(number))
    if parts:
        parts.append(f"{exception_type}: {exception_message}".strip())
        return "\n".join(parts)
    if exception_message:
        return f"{exception_type}: {exception_message}"
    return "No traceback available"


# Register the parser
PARSER_REGISTRY.register(PytestParser())
