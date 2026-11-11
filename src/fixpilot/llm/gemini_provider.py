"""FixPilot AI Gemini LLM provider.

This module is kept for backwards compatibility. The canonical
implementation now lives in :mod:`fixpilot.llm.provider`, so that there is
exactly one ``GeminiProvider`` class in the codebase (previously this module
defined a second, subtly different one and ``fixpilot.llm.GeminiProvider``
resolved to a different class than the one the workflow engine used).

Responsibilities:
- Integrate Gemini API behind configurable model.
- Handle provider errors, rate limits, timeouts, and malformed output.
- Support structured output for investigator and other agents.
- Mock provider in tests (no live API required).
"""

from fixpilot.llm.provider import (
    BaseLLMProvider,
    GeminiProvider,
    LLMOutputValidationError,
    LLMProviderError,
)

__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "LLMProviderError",
    "LLMOutputValidationError",
]
