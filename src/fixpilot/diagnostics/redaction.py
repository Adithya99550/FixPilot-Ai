"""FixPilot AI redaction utilities.

Responsibilities:
- Redact sensitive data from diagnostic snippets and logs.
- Apply secret scanning/redaction to logs and snippets.
- Never include raw environment variables in prompts or reports.

The patterns below are deliberately *conservative*: a secret is replaced even
when the surrounding text looks unusual, because a leaked credential in a
report, a log file or an LLM prompt is far worse than an over-redacted
snippet.  Values that are too short to be a real credential are left alone
so that ordinary identifiers stay readable.
"""

import re
from typing import List, Tuple

#: Common secret patterns to redact.
#:
#: Each entry is ``(pattern, replacement)``.  The second capturing group of
#: every pattern is the *secret value* and is replaced as a whole, so the
#: surrounding key name stays readable in the output.
SECRET_PATTERNS: List[Tuple[str, str]] = [
    # API keys and tokens
    (
        r"(?i)\b([a-z0-9_\-]*api[_-]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_]{12,})['\"]?",
        r"\1=[REDACTED_API_KEY]",
    ),
    (
        r"(?i)\b([a-z0-9_\-]*(?:auth|access|secret)[_-]?token)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_\.]{12,})['\"]?",
        r"\1=[REDACTED_TOKEN]",
    ),
    (
        r"(?i)\b(git[_-]?token)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_]{20,})['\"]?",
        r"\1=[REDACTED_GIT_TOKEN]",
    ),
    (
        r"(?i)\b([a-z0-9_\-]*pyramid[_-]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_]{12,})['\"]?",
        r"\1=[REDACTED_PYRAMID_KEY]",
    ),
    (
        r"(?i)\b([a-z0-9_\-]*secret[a-z0-9_\-]*)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_\.]{8,})['\"]?",
        r"\1=[REDACTED_SECRET]",
    ),
    (
        r"(?i)\b(password|passwd|pwd)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_\.]{6,})['\"]?",
        r"\1=[REDACTED_PASSWORD]",
    ),
    # Bearer / basic authorization headers
    (
        r"(?i)\b(bearer|basic)\s+([a-zA-Z0-9\-_\.\+/=]{12,})",
        r"\1 [REDACTED_AUTH]",
    ),
    # AWS style access key ids
    (r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b", "[REDACTED_AWS_KEY]"),
    # Private key blocks
    (
        r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)(?:.|\n)*?(-----END [A-Z ]*PRIVATE KEY-----)",
        r"\1[REDACTED_PRIVATE_KEY]\2",
    ),
    # URLs with credentials
    (r"(?i)(://[^\s@:/]+:[^\s@:/]+@)", "[REDACTED_URL_CREDS]"),
    # Email addresses (partial redaction)
    (r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[email protected]"),
]


def redact_sensitive_data(text: str) -> str:
    """Redact sensitive values from text.

    Args:
        text: Input text that may contain sensitive values.

    Returns:
        Text with sensitive values redacted.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.DOTALL)

    # Also truncate overly long values that might contain secrets
    # Keep first 8 and last 5 chars of any perceived token.
    result = re.sub(
        r"(['\"][a-zA-Z0-9\-_]{32,})['\"]",
        lambda m: (
            m.group(1)[:8] + "..." + m.group(1)[-5:]
            if len(m.group(1)) > 12
            else "[REDACTED]"
        ),
        result,
    )

    return result
