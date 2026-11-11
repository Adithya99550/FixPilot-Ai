"""Shared pytest fixtures for the FixPilot test suite."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Make ``src`` importable even when the package has not been installed with
# ``pip install -e .`` (e.g. when running the tests straight from a checkout).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class FakeLLMProvider:
    """A deterministic LLM provider used across the test suite."""

    def __init__(self, responses: Optional[List[str]] = None, error: Optional[Exception] = None):
        self.responses = list(responses or [])
        self.error = error
        self.prompts: List[str] = []
        self.calls = 0
        self._index = 0

    def _next(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.responses:
            return ""
        # The responses are consumed in order; the last one is reused once
        # the queue is exhausted so a test can script a fixed sequence.
        response = self.responses[min(self._index, len(self.responses) - 1)]
        self._index += 1
        return response

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens=None) -> str:
        return self._next(prompt)

    def generate_structured(
        self,
        prompt: str,
        output_schema: type,
        temperature: float = 0.7,
        max_tokens=None,
    ) -> Dict[str, Any]:
        raw = self._next(prompt)
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def supports_structured_output(self) -> bool:
        return True

    def validate_response(self, response: str) -> bool:
        return bool(response and response.strip())


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    """A fake LLM provider with an empty response queue."""
    return FakeLLMProvider()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A disposable workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws
