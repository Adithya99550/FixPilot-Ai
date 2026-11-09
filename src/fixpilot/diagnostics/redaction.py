"""FixPilot AI redaction utilities.

Responsibilities:
- Redact sensitive data from diagnostic snippets and logs.
- Apply secret scanning/redaction to logs and snippets.
- Never include raw environment variables in prompts or reports.
"""

import re
from typing import Optional


# Common secret patterns to redact
SECRET_PATTERNS = [
    # API keys and tokens
    (r"(?i)(api[_-]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_]{20,})", "[REDACTED_API_KEY]"),
    (r"(?i)(auth[_-]?token)\s*[:=]\s*['\"]?([a-zA-Z0-9\-\.]{20,})", "[REDACTED_TOKEN]"),
    (r"(?i)(git[_-]?token)\s*[:=]\s*['\"]?([a-zA-Z0-9\-\_]{40,})", "[REDACTED_GIT_TOKEN]"),
    (r"(?i)(py[_-]?ramid[_-]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9\-\_]{20,})", "[REDACTED_PYRAMID_KEY]"),
    (r"(?i)(secret)\s*[:=]\s*['\"]?([a-zA-Z0-9\-\_\.]{10,})", "[REDACTED_SECRET]"),
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([a-zA-Z0-9\-\_\.]{6,})", "[REDACTED_PASSWORD]"),
    # URLs with credentials
    (r"(?i)(://[^\s@]+:[^\s@]+@)", "[REDACTED_URL_CREDS]"),
    # Email addresses (partial redaction)
    (r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[email protected]"),
]


def redact_sensitive_data(text: str) -> str:
    """Redact sensitive values from text.

    Args:
        text: Input text that may contain sensitive values

    Returns:
        Text with sensitive values redacted
    """
    if not text:
        return text

    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result)

    # Also truncate overly long values that might contain secrets
    # Keep first 5 and last 5 chars of any perceived token
    result = re.sub(
        r"(['\"][a-zA-Z0-9\-_]{32,})['\"]",
        lambda m: m.group(1)[:8] + "..." + m.group(1)[-5:] if len(m.group(1)) > 12 else "[REDACTED]",
        result,
    )

    return result