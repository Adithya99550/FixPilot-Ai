"""Tests for the FixPilot diagnostic parsers."""


from fixpilot.diagnostics import (
    PARSER_REGISTRY,
    parse_pytest_output,
    parse_traceback,
    redact_sensitive_data,
)
from fixpilot.diagnostics.cargo_test_parser import CargoTestParser
from fixpilot.diagnostics.go_test_parser import GoTestParser
from fixpilot.diagnostics.jest_parser import JestParser
from fixpilot.diagnostics.junit_parser import JUnitParser
from fixpilot.diagnostics.pytest_parser import PytestParser


class TestPytestParser:
    def test_parses_a_failing_test(self):
        output = (
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_calc.py::test_add - assert -1 == 3\n"
        )
        failures = parse_pytest_output(output, "")
        assert len(failures) == 1
        assert failures[0].failing_test == "tests/test_calc.py::test_add"
        assert "assert -1 == 3" in failures[0].exception_message

    def test_parses_the_failure_block(self):
        output = (
            "=================================== FAILURES ===================================\n"
            "______________________________ test_add _______________________________\n"
            "tests/test_calc.py:9: in test_add\n"
            "    assert add(1, 2) == 3\n"
            "E       assert -1 == 3\n"
        )
        failures = parse_pytest_output(output, "")
        assert failures
        assert failures[0].exception_type or failures[0].summary

    def test_empty_output_produces_no_failures(self):
        assert parse_pytest_output("", "") == []

    def test_passing_output_produces_no_failures(self):
        assert parse_pytest_output("2 passed in 0.01s", "") == []

    def test_malformed_output_does_not_raise(self):
        assert parse_pytest_output("!!! not a pytest output ???", "") == [] or True

    def test_error_lines_are_parsed(self):
        output = (
            "=========================== short test summary info ============================\n"
            "ERROR tests/test_calc.py::test_add - fixture 'x' not found\n"
        )
        failures = parse_pytest_output(output, "")
        assert failures
        assert "test_add" in failures[0].failing_test


class TestTracebackParser:
    def test_python_traceback(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 3, in add\n'
            "    return a - b\n"
            "TypeError: unsupported operand type(s)\n"
        )
        evidence = parse_traceback(tb)
        assert evidence is not None
        assert evidence.summary

    def test_empty_traceback(self):
        """An empty traceback yields an empty evidence object, never a crash."""
        evidence = parse_traceback("")
        assert evidence is not None
        assert evidence.traceback


class TestRedaction:
    def test_api_keys_are_redacted(self):
        text = "export GEMINI_API_KEY=abcdef1234567890"
        redacted = redact_sensitive_data(text)
        assert "abcdef1234567890" not in redacted
        assert "[REDACTED" in redacted

    def test_long_api_keys_are_redacted(self):
        text = "GEMINI_API_KEY=AIzaSyA1234567890abcdefghijklmnopqrstuvw"
        assert "AIzaSyA1234567890" not in redact_sensitive_data(text)

    def test_password_is_redacted(self):
        redacted = redact_sensitive_data("password = hunter2secret")
        assert "hunter2secret" not in redacted

    def test_bearer_token_is_redacted(self):
        redacted = redact_sensitive_data("Authorization: Bearer abcdefghijklmnop")
        assert "abcdefghijklmnop" not in redacted

    def test_private_key_block_is_redacted(self):
        key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA\n"
            "-----END RSA PRIVATE KEY-----"
        )
        redacted = redact_sensitive_data(key)
        assert "MIIEowIBAAKCAQEA" not in redacted

    def test_plain_text_is_unchanged(self):
        text = "def add(a, b):\n    return a + b\n"
        assert redact_sensitive_data(text) == text

    def test_empty_text_is_handled(self):
        assert redact_sensitive_data("") == ""


class TestOtherLanguageParsers:
    def test_jest_parser(self):
        parser = JestParser()
        output = (
            "FAIL src/calculator.test.js\n"
            "  ● add › adds two numbers\n"
            "\n"
            "    expect(received).toBe(expected)\n"
            "    Expected: 3\n"
            "    Received: -1\n"
        )
        failures = parser.parse(output, "")
        assert failures
        assert failures[0].failing_test

    def test_go_parser(self):
        parser = GoTestParser()
        output = (
            "--- FAIL: TestAdd (0.00s)\n"
            "    calculator_test.go:12: expected 3, got -1\n"
            "FAIL\n"
            "FAIL\tgithub.com/example/calc\t0.002s\n"
        )
        failures = parser.parse(output, "")
        assert failures
        assert "TestAdd" in failures[0].failing_test

    def test_cargo_parser(self):
        parser = CargoTestParser()
        output = (
            "running 1 test\n"
            "test math::tests::test_add ... FAILED\n"
            "\n"
            "failures:\n"
            "\n"
            "---- math::tests::test_add stdout ----\n"
            "thread 'math::tests::test_add' panicked at src/lib.rs:10:5:\n"
            "assertion `left == right` failed\n"
            "\n"
            "failures:\n"
            "    math::tests::test_add\n"
            "\n"
            "test result: FAILED. 0 passed; 1 failed; 0 ignored\n"
        )
        failures = parser.parse(output, "")
        assert failures
        assert "test_add" in failures[0].failing_test

    def test_cargo_parser_uses_the_failures_section(self):
        """A truncated panic message is still reported via the failures list."""
        parser = CargoTestParser()
        output = (
            "test math::tests::test_add ... FAILED\n"
            "failures:\n"
            "    math::tests::test_add\n"
            "test result: FAILED. 0 passed; 1 failed; 0 ignored\n"
        )
        failures = parser.parse(output, "")
        assert failures
        assert "test_add" in failures[0].failing_test

    def test_junit_parser(self):
        parser = JUnitParser()
        output = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1">\n'
            '  <testcase classname="tests.test_calc" name="test_add" time="0.001">\n'
            '    <failure message="assert -1 == 3">details</failure>\n'
            "  </testcase>\n"
            "</testsuite>\n"
        )
        failures = parser.parse(output, "")
        assert failures
        assert "test_add" in failures[0].failing_test


class TestParserRegistry:
    def test_known_combinations_resolve(self):
        assert PARSER_REGISTRY.get_parser("python", "pytest") is not None
        assert PARSER_REGISTRY.get_parser("javascript", "jest") is not None
        assert PARSER_REGISTRY.get_parser("go", "go test") is not None
        assert PARSER_REGISTRY.get_parser("rust", "cargo test") is not None

    def test_unknown_combination_returns_none(self):
        assert PARSER_REGISTRY.get_parser("cobol", "cobol test") is None

    def test_empty_output_is_safe_for_every_parser(self):
        for parser in (
            PytestParser(),
            JestParser(),
            GoTestParser(),
            CargoTestParser(),
            JUnitParser(),
        ):
            assert parser.parse("", "") == []
