"""FixPilot AI JUnit output parser.

Responsibilities:
- Parse JUnit XML output and extract failure information.
- Extract exception type, message, file, line, stack frames, failing test.
- Produce structured diagnostic evidence.
"""

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from fixpilot.schemas.diagnostics import DiagnosticEvidence
from fixpilot.diagnostics.base import DiagnosticParser, PARSER_REGISTRY


class JUnitParser(DiagnosticParser):
    """Parser for JUnit XML output."""

    @property
    def language(self) -> str:
        return "java"

    @property
    def test_framework(self) -> str:
        return "junit"

    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse JUnit XML output and extract failure information."""
        failures = []

        # Try to find JUnit XML in the output
        # JUnit XML might be embedded in output or written to a file
        xml_content = self._extract_xml(output)
        if not xml_content and stderr:
            xml_content = self._extract_xml(stderr)

        if not xml_content:
            # Fall back to parsing text output
            return self._parse_text_output(output + "\n" + stderr)

        try:
            root = ET.fromstring(xml_content)
            # Handle both <testsuite> and <testsuites> root
            if root.tag == "testsuites":
                for testsuite in root.findall("testsuite"):
                    failures.extend(self._parse_testsuite(testsuite))
            elif root.tag == "testsuite":
                failures.extend(self._parse_testsuite(root))
        except ET.ParseError:
            # Fall back to text parsing
            return self._parse_text_output(output + "\n" + stderr)

        return failures

    def _extract_xml(self, text: str) -> Optional[str]:
        """Extract XML content from text output."""
        # Look for XML declaration or testsuites/testsuite tags
        xml_start = text.find("<?xml")
        if xml_start == -1:
            xml_start = text.find("<testsuites")
        if xml_start == -1:
            xml_start = text.find("<testsuite")

        if xml_start == -1:
            return None

        # Find the end of the XML
        xml_end = text.find("</testsuites>", xml_start)
        if xml_end == -1:
            xml_end = text.find("</testsuite>", xml_start)

        if xml_end == -1:
            return None

        return text[xml_start:xml_end + len("</testsuites>") if "</testsuites>" in text[xml_start:xml_end + 13] else xml_end + len("</testsuite>")]

    def _parse_testsuite(self, testsuite: ET.Element) -> List[DiagnosticEvidence]:
        """Parse a testsuite element for failures."""
        failures = []

        for testcase in testsuite.findall("testcase"):
            failure = testcase.find("failure")
            error = testcase.find("error")

            if failure is not None or error is not None:
                test_name = testcase.get("name", "unknown")
                class_name = testcase.get("classname", "")
                full_test_name = f"{class_name}.{test_name}" if class_name else test_name

                # Get failure/error details
                failure_elem = failure if failure is not None else error
                failure_type = failure_elem.get("type", "AssertionError")
                failure_message = failure_elem.get("message", "")
                failure_text = failure_elem.text or ""

                # Combine message and text
                full_message = f"{failure_message}\n{failure_text}".strip()

                # Try to extract file and line from stack trace
                file_path = ""
                line_num = 0
                if failure_text:
                    file_path, line_num = self._extract_location(failure_text)

                failures.append(self._build_evidence(
                    full_test_name, full_message, failure_type, file_path, line_num
                ))

        return failures

    def _extract_location(self, stack_trace: str) -> tuple:
        """Extract file path and line number from Java stack trace."""
        # Java stack trace pattern: "at package.Class.method(File.java:123)"
        patterns = [
            r"at\s+[\w\.$]+\s+\((\S+\.java):(\d+)\)",
            r"at\s+[\w\.$]+\s+\((\S+\.kt):(\d+)\)",
            r"(\S+\.java):(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, stack_trace)
            if match:
                return match.group(1), int(match.group(2))

        return "", 0

    def _parse_text_output(self, output: str) -> List[DiagnosticEvidence]:
        """Fallback: parse text output for test failures."""
        failures = []
        lines = output.split("\n")

        # Look for patterns like:
        # Tests run: 10, Failures: 2, Errors: 1, Skipped: 0
        # <<< FAILURE!
        # testMethod(com.example.TestClass)  Time elapsed: 0.123 s  <<< FAILURE!
        # java.lang.AssertionError: expected:<1> but was:<2>
        #     at com.example.TestClass.testMethod(TestClass.java:10)

        current_test = None
        current_error = ""
        current_type = "AssertionError"
        current_file = ""
        current_line = 0
        in_stack = False

        for line in lines:
            # Match test failure line: "testMethod(com.example.TestClass)  Time elapsed: 0.123 s  <<< FAILURE!"
            # OR: "com.example.TestClass.testMethod -- Time elapsed: 0.123 s  <<< FAILURE!"
            fail_match = re.match(
                r"^(\w+)\(([\w\.]+)\)\s+Time elapsed:.*<<< (FAILURE|ERROR)!$", line
            ) or re.match(
                r"^([\w\.]+)\.(\w+)\s+--\s+Time elapsed:.*<<< (FAILURE|ERROR)!$", line
            )
            if fail_match:
                # Save previous
                if current_test and current_error:
                    failures.append(self._build_evidence(
                        current_test, current_error, current_type, current_file, current_line
                    ))
                # Pattern 1: testMethod(className) - group(1) is method, group(2) is class
                # Pattern 2: className.methodName -- Time elapsed... - group(1) is class, group(2) is method
                if "." in fail_match.group(1):
                    # Pattern 2 matched
                    current_test = f"{fail_match.group(1)}.{fail_match.group(2)}"
                else:
                    # Pattern 1 matched
                    current_test = f"{fail_match.group(2)}.{fail_match.group(1)}"
                current_type = "Error" if fail_match.group(3) == "ERROR" else "AssertionError"
                current_error = ""
                current_file = ""
                current_line = 0
                in_stack = False
                continue

            # Match exception type: "java.lang.AssertionError: message"
            exc_match = re.match(r"^(\w+(?:\.\w+)*)(?:Error|Exception):\s*(.+)$", line.strip())
            if exc_match and current_test and not current_error:
                current_type = exc_match.group(1).split(".")[-1]
                current_error = exc_match.group(2)
                continue

            # Match stack trace: "    at com.example.TestClass.testMethod(TestClass.java:10)" (supports tabs and spaces)
            # Method name may be immediately followed by "(" with no space
            stack_match = re.match(r"^\s*at\s+[\w\.$]+\((\S+\.(?:java|kt)):(\d+)\)", line)
            if stack_match and current_test:
                file_path = stack_match.group(1)
                line_num = int(stack_match.group(2))
                # Prefer the test class file over internal library frames
                if "Test" in file_path and (not current_file or "Assertion" in current_file):
                    current_file = file_path
                    current_line = line_num
                elif not current_file:
                    current_file = file_path
                    current_line = line_num
                in_stack = True
                continue

            # Continuation of error message
            if current_test and current_error and not in_stack and line.strip() and not line.startswith("at "):
                current_error += "\n" + line.strip()

        # Save last
        if current_test and current_error:
            failures.append(self._build_evidence(
                current_test, current_error, current_type, current_file, current_line
            ))

        return failures

    def _build_evidence(self, test_name: str, error: str, exc_type: str, file_path: str, line_num: int):
        """Build DiagnosticEvidence from parsed data."""
        traceback_str = f'File "{file_path}", line {line_num}' if file_path else "No traceback available"
        line_range = (line_num, line_num) if line_num > 0 else (0, 0)
        file_refs = [file_path] if file_path else []

        return DiagnosticEvidence(
            summary=f"Test '{test_name}' failed",
            exception_type=exc_type,
            exception_message=error,
            failing_test=test_name,
            traceback=traceback_str,
            file_references=file_refs,
            line_range=line_range,
            snippet="",
            redacting=False,
            language="java",
            test_framework="junit",
        )


# Register the parser
PARSER_REGISTRY.register(JUnitParser())