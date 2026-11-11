"""Unit tests for FixPilot AI Investigator Agent."""

import json
from typing import Any, Dict


from fixpilot.agents.investigator import Investigator
from fixpilot.schemas.investigation import InvestigationResult


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response_data: Dict[str, Any]):
        self._response_data = response_data

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens=None) -> str:
        """Return pre-defined response."""
        return json.dumps(self._response_data)

    def generate_structured(
        self,
        prompt: str,
        output_schema: type,
        temperature: float = 0.7,
        max_tokens=None,
    ) -> Dict[str, Any]:
        """Return pre-defined response."""
        return self._response_data

    @property
    def model_name(self) -> str:
        return "test-model"

    @property
    def supports_structured_output(self) -> bool:
        return True

    def validate_response(self, response: str) -> bool:
        return True


class TestInvestigator:
    """Tests for the Investigator agent."""

    def test_investigate_with_mocked_llm(self):
        """Test investigation with a mocked LLM provider."""
        # Arrange
        mock_provider = MockLLMProvider({
            "summary": "Test add_numbers failed due to type mismatch",
            "root_cause_hypotheses": [
                {
                    "explanation": "The add_numbers function received a string '2' instead of an integer",
                    "confidence": "high",
                    "evidence": ["src/fixpilot/sample_projects/type_error/add_numbers.py:15"],
                    "affected_files": ["src/fixpilot/sample_projects/type_error/add_numbers.py"],
                }
            ],
            "evidence": "Type check at line 14-17 in add_numbers.py",
            "affected_files": ["src/fixpilot/sample_projects/type_error/add_numbers.py"],
            "missing_information": ["Full test output details"],
            "recommended_next_action": "plan_repair",
            "confidence": "high",
            "limitations": ["Limited test output available"],
        })

        investigator = Investigator(mock_provider)

        diagnostics = {
            "test_output": "FAILED test_add_numbers_type_error",
            "stderr": "",
            "traceback": "",
            "failing_test": "test_add_numbers_type_error",
        }

        project_metadata = {
            "affected_files": ["src/fixpilot/sample_projects/type_error/add_numbers.py"],
            "test_summary": "type_error tests",
        }

        config = {}

        # Act
        result: InvestigationResult = investigator.investigate(
            diagnostics, project_metadata, config
        )

        # Assert
        assert result.summary == "Test add_numbers failed due to type mismatch"
        assert len(result.root_cause_hypotheses) == 1
        assert result.root_cause_hypotheses[0].confidence == "high"
        assert result.recommended_next_action == "plan_repair"
        assert result.confidence == "high"

    def test_investigate_no_llm(self):
        """Test investigation when LLM provider fails."""
        # Arrange
        from fixpilot.llm.provider import LLMProviderError

        class FailingProvider:
            def generate(self, prompt, temperature=0.7, max_tokens=None):
                raise LLMProviderError("API key missing")

            def generate_structured(self, prompt, output_schema, temperature=0.7, max_tokens=None):
                raise LLMProviderError("API key missing")

            @property
            def model_name(self):
                return "test-model"

            @property
            def supports_structured_output(self):
                return True

            def validate_response(self, response):
                return True

        investigator = Investigator(FailingProvider())

        diagnostics = {
            "test_output": "FAILED test_math_type_error",
            "stderr": "",
            "traceback": "",
            "failing_test": "test_math_type_error",
        }

        project_metadata = {
            "affected_files": [],
            "test_summary": "math tests",
        }

        config = {}

        # Act
        result: InvestigationResult = investigator.investigate(
            diagnostics, project_metadata, config
        )

        # Assert - should still return a valid result via fallback
        assert result is not None
        assert hasattr(result, "summary")
        assert hasattr(result, "recommended_next_action")

    def test_investigate_empty_failures(self):
        """Test investigation with no explicit failure info."""
        # Arrange
        mock_provider = MockLLMProvider({
            "summary": "No failing tests detected",
            "root_cause_hypotheses": [],
            "evidence": [],
            "affected_files": [],
            "missing_information": [],
            "recommended_next_action": "stop",
            "confidence": "low",
            "limitations": [],
        })

        investigator = Investigator(mock_provider)

        diagnostics = {
            "test_output": "",
            "stderr": "",
            "traceback": "",
            "failing_test": "",
        }

        project_metadata = {
            "affected_files": [],
            "test_summary": "no tests",
        }

        config = {}

        # Act
        result: InvestigationResult = investigator.investigate(
            diagnostics, project_metadata, config
        )

        # Assert
        assert result.recommended_next_action == "stop"
        assert result.confidence == "low"