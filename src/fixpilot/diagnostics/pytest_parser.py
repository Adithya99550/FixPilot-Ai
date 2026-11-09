"""FixPilot AI pytest output parser.

Responsibilities:
- Parse pytest output and Python tracebacks.
- Extract exception type, message, file, line, stack frames, failing test, and relevant snippets.
- Deduplicate repeated errors.
- Redact sensitive values.
- Produce structured diagnostic evidence.
"""

import re
from pathlib import Path
from fixpilot.schemas.diagnostics import DiagnosticEvidence


def parse_pytest_output(output: str, stderr: str = "") -> list:
    """Parse pytest output and extract failure information.

    Args:
        output: pytest stdout output
        stderr: pytest stderr output

    Returns:
        List of DiagnosticEvidence objects, one per failing test
    """
    failures = []

    # Combine output and stderr for analysis
    full_output = output + "\n" + stderr

    # Find failing test names from pytest summary lines
    failing_tests = _extract_failing_test_names(full_output)

    # For each failing test, try to extract detailed evidence
    for test_name in failing_tests:
        evidence = _extract_test_evidence(test_name, full_output)
        if evidence:
            failures.append(evidence)

    # If no explicitly failing tests found, check for any test references
    if not failures:
        # Try to find test names in the output
        test_name_pattern = re.compile(r'(test_\w+)', re.IGNORECASE)
        for line in full_output.split("\n"):
            matches = test_name_pattern.findall(line)
            for match in matches:
                test_name = match[0] if isinstance(match, tuple) else match
                if len(test_name) > 3 and test_name.startswith("test_"):
                    evidence = _extract_test_evidence(test_name, full_output)
                    if evidence and evidence not in failures:
                        failures.append(evidence)
                    if len(failures) >= 10:
                        return failures

    return failures


def _extract_failing_test_names(full_output: str) -> list:
    """Extract names of failing/passing tests from pytest output."""
    test_names = set()

    lines = full_output.split("\n")
    for line in lines:
        stripped = line.strip()

        # Match "FAILED test_name" at start of line
        match = re.match(r"FAILED\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            test_names.add(match.group(1).strip())

        # Match "ERROR test_name" at start of line
        match = re.match(r"ERROR\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            test_names.add(match.group(1).strip())

        # Match "FAIL test_name" at start of line
        match = re.match(r"FAIL\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            test_names.add(match.group(1).strip())

        # Match pytest short summary lines: "= FAILED test_name" or "F test_name"
        match = re.match(r"[=\-\+F]\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            test_names.add(match.group(1).strip())

    return list(test_names)


def _extract_test_evidence(test_name: str, full_output: str) -> dict:
    """Extract evidence for a specific failing test.

    Args:
        test_name: Name of the failing test
        full_output: Complete pytest output

    Returns:
        Dict with test failure information or None
    """
    # Find the line number where this test was mentioned
    test_line_idx = None
    lines = full_output.split("\n")
    for i, line in enumerate(lines):
        if test_name in line:
            test_line_idx = i
            break

    if test_line_idx is None:
        return None

    # Collect exception type and message
    exception_type = ""
    exception_message = ""

    # Search for exception patterns in the output
    for line in lines:
        # Match "TypeError: message", "ValueError: message", etc.
        match = re.match(r"^(\w+Error):\s+(.+)$", line, re.IGNORECASE)
        if match and not exception_type:
            exception_type = match.group(1)
            exception_message = match.group(2)

        # Match the re-raised exception at end of traceback
        if match and exception_type and ":" in match.group(2) and not line.strip().startswith("File"):
            # Don't override if we already have the exception info
            pass

    # Collect traceback frames
    frames = _extract_traceback_frames(full_output, lines)

    # Get code snippet around the failure
    snippet = _extract_snippet(lines, test_line_idx)

    # Redact sensitive values
    from fixpilot.diagnostics.redaction import redact_sensitive_data

    redacted_snippet = redact_sensitive_data(snippet) if snippet else ""
    redacted_message = (
        redact_sensitive_data(exception_message) if exception_message else ""
    )

    # Build file references from frames
    file_refs = [f["file"] for f in frames[:5]]

    # Build line range
    if frames:
        line_range = (frames[0]["line"], frames[-1]["line"])
    else:
        line_range = (test_line_idx + 1, test_line_idx + 1)

    evidence = DiagnosticEvidence(
        summary=f"Test '{test_name}' failed",
        exception_type=exception_type or "AssertionError",
        exception_message=redacted_message or "Test assertion failed",
        failing_test=test_name,
        traceback=_build_traceback(frames),
        file_references=file_refs,
        line_range=line_range,
        snippet=redacted_snippet,
        redacting=bool(snippet or exception_message),
    )

    return evidence


def _extract_traceback_frames(full_output: str, lines: list) -> list:
    """Extract traceback frames from pytest output."""
    frames = []
    in_traceback = False

    for line in lines:
        # Start of traceback
        if "Traceback (most recent call last)" in line:
            in_traceback = True
            continue

        if in_traceback:
            # Frame line: "  File \"path\", line N, in function"
            frame_match = re.match(r'  File "([^"]*)", line (\d+), in (.+)', line)
            if frame_match:
                frames.append(
                    {
                        "file": frame_match.group(1),
                        "line": int(frame_match.group(2)),
                        "function": frame_match.group(3),
                    }
                )
                continue

            # End of traceback: exception re-line or blank line after frames
            # Check if this looks like the exception type line at the end
            if re.match(r"\s+\w+Error:\s+.+", line) and frames:
                # This is the exception re-line at the end of traceback
                # Don't add it as a frame, stop collecting
                in_traceback = False
                continue

            # If line doesn't start with spaces and isn't empty, end traceback
            if line.strip() and not line.startswith("  ") and not line.startswith("\t"):
                in_traceback = False
                continue

    return frames


def _extract_snippet(lines: list, test_line_idx: int) -> str:
    """Extract a code snippet around the failing test line."""
    if test_line_idx is None:
        return ""

    # Collect context: 3 lines before and 2 lines after the test reference
    start = max(0, test_line_idx - 3)
    end = min(len(lines), test_line_idx + 3)
    context_lines = lines[start:end]

    snippet = "\n".join(context_lines)
    return snippet


def _build_traceback(frames: list) -> str:
    """Build a traceback string from frames list."""
    if not frames:
        return "No traceback available"

    parts = []
    for f in frames:
        parts.append('File "' + f["file"] + '", line ' + str(f["line"]) + ', in ' + f["function"])
    return "\n".join(parts)


def _detect_test_command(full_output: str, config: dict) -> str:
    """Detect the test command from configuration or output."""
    # Check configured test command first
    configured = config.get("test_command")
    if configured:
        return str(configured)

    # Default
    return "python -m pytest -q"