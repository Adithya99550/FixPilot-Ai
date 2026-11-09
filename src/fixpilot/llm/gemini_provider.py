"""FixPilot AI Gemini LLM provider.

Responsibilities:
- Integrate Gemini API behind configurable model.
- Handle provider errors, rate limits, timeouts, and malformed output.
- Support structured output for investigator and other agents.
- Mock provider in tests (no live API required).
"""

import os
from typing import Any, Dict, Optional

from fixpilot.llm.provider import BaseLLMProvider, LLMProviderError, LLMOutputValidationError


class GeminiProvider(BaseLLMProvider):
    """Gemini API provider implementation for FixPilot AI."""

    def __init__(self, api_key: Optional[str] = None, model: str = None):
        """Initialize the Gemini provider.

        Args:
            api_key: Gemini API key. If None, reads from GEMINI_API_KEY env var.
            model: Model name. If None, reads from FIXPILOT_MODEL env var.
        """
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model or os.getenv("FIXPILOT_MODEL", "gemini-1.5-flash")
        self._client = None

        # Try to import generativeai
        try:
            import google.generativeai as genai

            if self._api_key:
                genai.configure(api_key=self._api_key)
            self._client = genai
        except ImportError:
            pass

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_structured_output(self) -> bool:
        return True

    def _ensure_client(self) -> None:
        """Ensure the Gemini client is available."""
        if self._client is None:
            raise LLMProviderError(
                "Google Generative AI package not available. "
                "Install: pip install google-generativeai\n"
                "Or set GEMINI_API_KEY with a valid API key."
            )

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens=None) -> str:
        """Generate text from Gemini API."""
        self._ensure_client()

        try:
            import google.generativeai as genai

            model = genai.GenerativeModel(self._model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )

            if response.text:
                return response.text
            elif response.prompt_feedback and response.prompt_feedback.block_reason:
                raise LLMProviderError(
                    f"Prompt blocked: {response.prompt_feedback.block_reason}"
                )
            else:
                raise LLMProviderError("Empty response from Gemini API")
        except Exception as e:
            raise LLMProviderError(f"Gemini API error: {str(e)}")

    def generate_structured(
        self,
        prompt: str,
        output_schema: type,
        temperature: float = 0.7,
        max_tokens=None,
    ) -> Dict[str, Any]:
        """Generate structured output from Gemini API.

        Tries to parse the raw response as JSON and validate against the schema.
        """
        raw_response = self.generate(prompt, temperature, max_tokens)

        # Try to parse as JSON
        import json

        try:
            # Try direct JSON parse first
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            # Look for the first { ... } block
            start = raw_response.find("{")
            end = raw_response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = raw_response[start:end]
                parsed = json.loads(json_str)
            else:
                raise LLMOutputValidationError(
                    "Could not find JSON in LLM response"
                )

        # Validate that required fields are present
        # This is a simplified check; full pydantic validation would be done later
        if not isinstance(parsed, dict):
            raise LLMOutputValidationError("Structured response is not a JSON object")

        return parsed