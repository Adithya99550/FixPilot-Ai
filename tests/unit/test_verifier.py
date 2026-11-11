"""Tests for the FixPilot Verifier agent."""


from fixpilot.agents.verifier import Verifier
from fixpilot.schemas.execution import ExecutionResult


def _result(exit_code, stdout="", stderr="", timed_out=False):
    return ExecutionResult(
        exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out
    )


FAILING = (
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_calc.py::test_add - assert -1 == 3\n"
)

TWO_FAILING = (
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_calc.py::test_add - assert -1 == 3\n"
    "FAILED tests/test_calc.py::test_sub - assert 5 == 1\n"
)

PASSING = "============================= 2 passed in 0.01s ==============================\n"

SUB_ONLY_FAILING = (
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_calc.py::test_sub - assert 5 == 1\n"
)

CONFIG = {"language": "python", "test_framework": "pytest"}


class TestSuccessRequiresEvidence:
    def test_all_tests_pass_is_success(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING), _result(0, PASSING), _result(1, FAILING), CONFIG
        )
        assert outcome["status"] == "success"
        assert outcome["new_failures"] == []

    def test_timeout_is_not_success(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING),
            _result(-1, timed_out=True),
            _result(1, FAILING),
            CONFIG,
        )
        assert outcome["status"] == "stop"
        assert "timed out" in outcome["evidence"].lower()

    def test_infrastructure_failure_is_not_success(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(-1), _result(-1), _result(-1), CONFIG
        )
        assert outcome["status"] == "stop"
        assert "infrastructure" in outcome["evidence"].lower()

    def test_original_failures_fixed_is_success(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING), _result(1, PASSING), _result(1, FAILING), CONFIG
        )
        # exit code is 0 in PASSING -> success
        assert outcome["status"] == "success"

    def test_new_failure_is_a_regression(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING), _result(1, TWO_FAILING), _result(1, FAILING), CONFIG
        )
        assert outcome["status"] == "regression"
        assert "tests/test_calc.py::test_sub" in outcome["new_failures"]

    def test_partial_progress_is_a_partial(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, TWO_FAILING), _result(1, FAILING), _result(1, TWO_FAILING), CONFIG
        )
        assert outcome["status"] == "partial"
        assert outcome["failure_kind"] == "partial_progress"
        assert outcome["previously_failing_now_passing"]

    def test_collection_error_is_not_a_regression(self):
        """A patch that breaks the file makes the suite uncollectable.

        That is a *patch* problem, not a regression: the tests never ran, so
        there is nothing to compare with the baseline.
        """
        verifier = Verifier()
        collection_error = (
            "=================================== ERRORS ====================================\n"
            "__________________ ERROR collecting tests/test_calc.py __________________\n"
            "E   IndentationError: expected an indented block after 'for' statement\n"
            "=========================== short test summary info ============================\n"
            "ERROR tests/test_calc.py\n"
            "!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
        )
        outcome = verifier.verify(
            _result(1, FAILING),
            _result(2, collection_error),
            _result(1, FAILING),
            CONFIG,
        )
        assert outcome["status"] == "stop"
        assert outcome["failure_kind"] == "suite_not_executed"
        assert outcome["new_failures"] == []
        assert "could not be executed" in outcome["evidence"].lower()

    def test_usage_error_is_not_a_regression(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING), _result(4, "ERROR: file or directory not found"),
            _result(1, FAILING), CONFIG,
        )
        assert outcome["status"] == "stop"
        assert outcome["failure_kind"] == "suite_not_executed"

    def test_no_progress_is_a_stop(self):
        verifier = Verifier()
        outcome = verifier.verify(
            _result(1, FAILING), _result(1, FAILING), _result(1, FAILING), CONFIG
        )
        assert outcome["status"] == "stop"

    def test_acceptable_new_failures_can_still_succeed(self):
        verifier = Verifier()
        config = dict(CONFIG)
        config["acceptable_new_failures"] = ["tests/test_calc.py::test_sub"]
        outcome = verifier.verify(
            _result(1, FAILING),
            _result(1, SUB_ONLY_FAILING),
            _result(1, FAILING),
            config,
        )
        assert outcome["status"] == "success"
        assert outcome["new_failures"] == ["tests/test_calc.py::test_sub"]

    def test_acceptable_new_failures_do_not_hide_unresolved_failures(self):
        verifier = Verifier()
        config = dict(CONFIG)
        config["acceptable_new_failures"] = ["tests/test_calc.py::test_sub"]
        outcome = verifier.verify(
            _result(1, FAILING),
            _result(1, TWO_FAILING),
            _result(1, FAILING),
            config,
        )
        assert outcome["status"] == "stop"


class TestParserSelection:
    def test_unknown_language_falls_back_to_pytest(self):
        verifier = Verifier()
        parser = verifier._get_parser({"language": "", "test_framework": ""})
        assert parser is not None
        assert parser.language == "python"

    def test_known_language_uses_its_parser(self):
        verifier = Verifier()
        parser = verifier._get_parser({"language": "javascript", "test_framework": "jest"})
        assert parser is not None
        assert parser.language == "javascript"
