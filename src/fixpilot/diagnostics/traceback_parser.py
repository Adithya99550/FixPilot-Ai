"""FixPilot AI traceback parser.

Responsibilities:
- Parse Python tracebacks from exception output.
- Extract exception type, message, file, line, stack frames, and relevant snippets.
- Deduplicate repeated errors.
- Redact sensitive values.
"""

import re
from pathlib import Path
from fixpilot.schemas.diagnostics import DiagnosticEvidence


def parse_traceback(output: str) -> DiagnosticEvidence:
    """Parse a Python traceback and extract structured diagnostic evidence.

    Args:
        output: Raw traceback/output text from Python exception

    Returns:
        DiagnosticEvidence object with parsed information
    """
    exception_type = ""
    exception_message = ""
    traceback_frames = []
    snippet = ""

    lines = output.split("\n") if output else []

    # Parse exception type and message from the first line
    # Format: "TypeError: message" or "NameError: name 'x' is not defined"
    if lines:
        first_line = lines[0].strip()
        # Split on the first colon to get type and message
        colon_idx = first_line.find(":")
        if colon_idx > 0:
            exception_type = first_line[:colon_idx].strip()
            exception_message = first_line[colon_idx + 1:].strip()
        else:
            exception_type = first_line
            exception_message = ""

    # Parse traceback frames
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
                traceback_frames.append(
                    {
                        "file": frame_match.group(1),
                        "line": int(frame_match.group(2)),
                        "function": frame_match.group(3),
                    }
                )
                # Check if this is the exception re-line at the end
                if re.match(r"\s+\w+Error:\s+.+", line) and traceback_frames:
                    # Exception re-line at end of traceback - stop collecting
                    in_traceback = False
                    continue

            # If line doesn't start with spaces and isn't empty, end traceback
            if line.strip() and not line.startswith("  ") and not line.startswith("\t"):
                in_traceback = False
                continue

    # Extract code snippet from the failed file/line
    if traceback_frames:
        file_path = traceback_frames[0]["file"]
        failure_line = traceback_frames[0]["line"]
        try:
            path = Path(file_path)
            if path.exists():
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                    if 0 <= failure_line - 1 < len(all_lines):
                        # Get a snippet of 3 lines: before, current, after
                        start = max(0, failure_line - 2 - 1)
                        end = min(len(all_lines), failure_line + 1)
                        snippet_lines = all_lines[start:end]
                        snippet = "".join(snippet_lines)
        except Exception:
            pass

    # Redact sensitive values from snippet and message
    from fixpilot.diagnostics.redaction import redact_sensitive_data

    redacted_snippet = redact_sensitive_data(snippet) if snippet else ""
    redacted_message = redact_sensitive_data(exception_message) if exception_message else ""

    # Build file references
    file_references = [f["file"] for f in traceback_frames[:5]]

    # Build line range
    if traceback_frames:
        line_range = (traceback_frames[0]["line"], traceback_frames[-1]["line"])
    else:
        line_range = (0, 0)

    return DiagnosticEvidence(
        summary=f"{exception_type}: {exception_message}" if exception_type else "Unknown error",
        exception_type=exception_type,
        exception_message=redacted_message,
        failing_test="",
        traceback=_build_traceback_str(traceback_frames),
        file_references=file_references,
        line_range=line_range,
        snippet=redacted_snippet,
        redacting=bool(snippet or exception_message),
    )


def _build_traceback_str(frames: list) -> str:
    """Build a traceback string from frames list."""
    if not frames:
        return "No traceback available"

    parts = []
    for f in frames:
        part = "File " + '"' + f["file"] + '"' ", line " + str(f["line"]) + ", in " + f["function"]
        parts.append(part)
    return "\n".join(parts)