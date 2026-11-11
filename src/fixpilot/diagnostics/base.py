"""FixPilot AI diagnostics parser base.

Defines the abstract base class for diagnostic parsers.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from fixpilot.schemas.diagnostics import DiagnosticEvidence


class DiagnosticParser(ABC):
    """Abstract base class for diagnostic parsers.

    Each language/test framework combination should implement a parser
    that can extract structured diagnostic evidence from test output.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Language this parser handles (e.g., 'python', 'javascript')."""
        pass

    @property
    @abstractmethod
    def test_framework(self) -> str:
        """Test framework this parser handles (e.g., 'pytest', 'jest')."""
        pass

    @abstractmethod
    def parse(self, output: str, stderr: str = "") -> List[DiagnosticEvidence]:
        """Parse test output and extract diagnostic evidence.

        Args:
            output: Test runner stdout output
            stderr: Test runner stderr output

        Returns:
            List of DiagnosticEvidence objects, one per failure
        """
        pass

    def _get_config_files(self) -> List[str]:
        """Get config files this parser understands."""
        return []


class ParserRegistry:
    """Registry for diagnostic parsers."""

    def __init__(self):
        self._parsers: List[DiagnosticParser] = []

    def register(self, parser: DiagnosticParser):
        """Register a parser."""
        self._parsers.append(parser)

    def get_parser(self, language: str, test_framework: str) -> Optional[DiagnosticParser]:
        """Get a parser for a specific language and test framework."""
        for parser in self._parsers:
            if parser.language == language and parser.test_framework == test_framework:
                return parser
        # Fallback: try language only
        for parser in self._parsers:
            if parser.language == language:
                return parser
        return None

    def list_parsers(self) -> List[tuple]:
        """List all registered parsers as (language, test_framework) tuples."""
        return [(p.language, p.test_framework) for p in self._parsers]


# Global parser registry
PARSER_REGISTRY = ParserRegistry()