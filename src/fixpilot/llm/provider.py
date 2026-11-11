"""FixPilot AI LLM provider abstraction.

Responsibilities:
- Define the provider interface/contract for LLM interactions.
- Abstract away provider-specific details (API calls, response formatting).
- Handle provider errors, rate limits, timeouts, and malformed output.
- Support mockable interface for testing without live API keys.
- Redact secrets and sensitive values from prompts and responses.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


# The `google.generativeai` package is deprecated in favour of `google-genai`.
# It still works, but importing it prints a multi-line warning on every CLI
# invocation, which drowns out the actual command output.
import warnings

# NOTE: the warning message starts with newlines, so the pattern has to be
# able to cross line boundaries (``.`` does not match "\n").
warnings.filterwarnings(
    "ignore",
    message=r"[\s\S]*google\.generativeai[\s\S]*",
    category=FutureWarning,
)


class LLMProviderError(Exception):
    """Raised when an LLM provider fails or returns invalid output."""
    pass


class LLMOutputValidationError(LLMProviderError):
    """Raised when LLM output fails validation checks."""
    pass


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the model."""
        pass

    @property
    @abstractmethod
    def supports_structured_output(self) -> bool:
        """Whether this provider supports structured output mode."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from the LLM provider.

        Args:
            prompt: The prompt to send to the LLM.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum tokens to generate.

        Returns:
            The generated text response.

        Raises:
            LLMProviderError: If the provider fails or times out.
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        output_schema: type,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate structured output from the LLM provider.

        Args:
            prompt: The prompt to send to the LLM.
            output_schema: Pydantic model class for expected output.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum tokens to generate.

        Returns:
            Dict validated against the output_schema.

        Raises:
            LLMProviderError: If the provider fails or output is invalid.
        """
        pass

    def validate_response(self, response: str) -> bool:
        """Validate that the provider response is well-formed.

        Args:
            response: The raw text response from the LLM.

        Returns:
            True if the response appears valid, False otherwise.
        """
        return response is not None and len(response.strip()) > 0


class GeminiProvider(BaseLLMProvider):
    """Gemini API provider implementation.

    Wraps the Google Gemini API with proper error handling,
    prompt formatting, and structured output support.
    """

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        """Initialize the Gemini provider.

        Args:
            api_key: Gemini API key from environment.
            model: Model name (e.g. 'gemini-1.5-flash', 'gemini-1.0-pro').
        """
        import os

        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model
        # Check if genai is available
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key, transport="rest")
            self._genai = genai
        except ImportError:
            self._genai = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_structured_output(self) -> bool:
        return True

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens=None) -> str:
        """Generate text from Gemini API."""
        if not self._genai:
            raise LLMProviderError(
                "Google Generative AI package not available. "
                "Install: pip install google-generativeai"
            )

        try:
            model = self._genai.GenerativeModel(self._model)
            response = model.generate_content(
                prompt,
                generation_config=self._genai.types.GenerationConfig(
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

        Args:
            prompt: The prompt to send to the LLM.
            output_schema: Pydantic model class for expected output.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum tokens to generate.

        Returns:
            Dict validated against the output_schema.

        Raises:
            LLMProviderError: If the provider fails or output is invalid.
        """
        raw_response = self.generate(prompt, temperature, max_tokens)

        # Try to parse the response as the expected schema
        try:
            # Attempt to parse as JSON if the schema expects it
            import json

            # Try parsing the raw response
            try:
                parsed = json.loads(raw_response)
            except json.JSONDecodeError:
                # If not JSON, try to extract JSON from the response
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

            # Validate against the schema - this is a simplified validation
            # In a full implementation, would use pydantic's model_validate
            if isinstance(parsed, dict):
                model_fields = getattr(output_schema, "model_fields", None)
                if model_fields is None:
                    # No Pydantic schema was supplied (e.g. `dict`), so the
                    # caller wants the raw parsed object.
                    return parsed
                return {k: v for k, v in parsed.items() if k in model_fields}
            return parsed

        except Exception as e:
            raise LLMProviderError(
                f"Failed to validate structured output: {str(e)}"
            )