"""FixPilot AI languages module.

Provides language configuration registry and detection.
"""

from fixpilot.languages.base import LanguageConfig
from fixpilot.languages.registry import (
    get_language_config,
    detect_language,
    detect_test_framework,
    list_supported_languages,
    LANGUAGE_CONFIGS,
)

__all__ = [
    "LanguageConfig",
    "get_language_config",
    "detect_language",
    "detect_test_framework",
    "list_supported_languages",
    "LANGUAGE_CONFIGS",
]