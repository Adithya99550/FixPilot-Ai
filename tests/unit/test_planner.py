"""Tests for the FixPilot Planner agent."""

import pytest

from fixpilot.agents.planner import Planner
from fixpilot.schemas.investigation import InvestigationResult, RootCauseHypothesis


def _investigation(files=None, hypotheses=None, summary="Something failed"):
    return InvestigationResult(
        summary=summary,
        root_cause_hypotheses=hypotheses or [],
        evidence=["file.py:1"],
        affected_files=files or [],
        missing_information=[],
        recommended_next_action="plan_repair",
        limitations=[],
        confidence="high",
    )


class TestCreatePlan:
    def test_valid_investigation_produces_a_plan(self):
        planner = Planner()
        investigation = _investigation(
            files=["calculator.py"],
            hypotheses=[
                RootCauseHypothesis(
                    explanation="add() subtracts",
                    confidence="high",
                    evidence=["calculator.py:2"],
                    affected_files=["calculator.py"],
                )
            ],
        )
        plan = planner.create_plan(investigation, {"language": "python"})
        assert plan.goal
        assert plan.root_cause == "add() subtracts"
        assert plan.steps
        assert "calculator.py" in plan.files_to_change
        assert plan.validation_command
        assert plan.language == "python"

    def test_empty_investigation_still_produces_a_plan(self):
        planner = Planner()
        plan = planner.create_plan(_investigation(), {})
        assert plan.goal
        assert plan.files_to_change == []
        assert plan.regression_risks

    def test_test_files_are_never_in_files_to_change(self):
        planner = Planner()
        investigation = _investigation(
            files=["tests/test_calculator.py"],
            hypotheses=[
                RootCauseHypothesis(
                    explanation="test bug",
                    confidence="low",
                    affected_files=["tests/test_calculator.py"],
                )
            ],
        )
        plan = planner.create_plan(investigation, {})
        assert "tests/test_calculator.py" not in plan.files_to_change
        assert "tests/test_calculator.py" in plan.files_not_to_change

    def test_test_file_is_mapped_to_the_source_file(self, tmp_path):
        (tmp_path / "calculator.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_calculator.py").write_text("x = 1\n", encoding="utf-8")
        planner = Planner()
        investigation = _investigation(files=["tests/test_calculator.py"])
        plan = planner.create_plan(investigation, {}, workspace_path=tmp_path)
        assert "calculator.py" in plan.files_to_change
        assert "tests/test_calculator.py" in plan.files_not_to_change

    def test_multiple_proposed_fixes_are_listed(self):
        planner = Planner()
        investigation = _investigation(
            files=["a.py", "b.py"],
            hypotheses=[
                RootCauseHypothesis(
                    explanation="multiple issues",
                    confidence="medium",
                    affected_files=["a.py", "b.py"],
                )
            ],
        )
        plan = planner.create_plan(investigation, {})
        assert "a.py" in plan.files_to_change
        assert "b.py" in plan.files_to_change

    def test_configured_exclusions_are_protected(self):
        planner = Planner()
        plan = planner.create_plan(_investigation(), {"exclude": ["secret_module.py"]})
        assert "secret_module.py" in plan.files_not_to_change

    def test_regression_risks_are_language_aware(self):
        planner = Planner()
        go_plan = planner.create_plan(_investigation(), {"language": "go"})
        python_plan = planner.create_plan(_investigation(), {"language": "python"})
        assert go_plan.regression_risks != python_plan.regression_risks
        assert any("Interface changes" in risk for risk in go_plan.regression_risks)


class TestDefaultCommands:
    @pytest.mark.parametrize(
        "language,framework,expected",
        [
            ("python", "pytest", "python -m pytest -q"),
            ("javascript", "jest", "npm test -- --passWithNoTests"),
            ("go", "go test", "go test ./..."),
            ("rust", "cargo test", "cargo test"),
            ("java", "maven", "mvn test"),
        ],
    )
    def test_default_validation_commands(self, language, framework, expected):
        planner = Planner()
        plan = planner.create_plan(
            _investigation(), {"language": language, "test_framework": framework}
        )
        assert plan.validation_command == expected
