"""FixPilot AI language configuration base.

Defines the LanguageConfig dataclass for multi-language support.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class LanguageConfig:
    """Configuration for a programming language.

    Attributes:
        name: Language identifier (e.g., 'python', 'javascript')
        extensions: File extensions for this language (e.g., ['.py'])
        test_patterns: Patterns to identify test files (e.g., ['test_*.py', '*_test.py'])
        config_files: Configuration files that indicate this language (e.g., ['pyproject.toml', 'package.json'])
        default_test_command: Default test command to run
        build_commands: List of build commands to run before tests
        sandbox_image: Docker image for sandboxed execution
        test_frameworks: Supported test frameworks for this language
        language_specific_flags: Additional flags for the language
        needs_network: Whether the language needs network access (e.g., Maven, Gradle, npm)
    """
    name: str
    extensions: List[str] = field(default_factory=list)
    test_patterns: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    default_test_command: List[str] = field(default_factory=list)
    build_commands: List[str] = field(default_factory=list)
    sandbox_image: str = ""
    test_frameworks: List[str] = field(default_factory=list)
    language_specific_flags: Dict[str, str] = field(default_factory=dict)
    needs_network: bool = False
    sandbox_image: str = ""
    test_frameworks: List[str] = field(default_factory=list)
    language_specific_flags: Dict[str, str] = field(default_factory=dict)

    def get_test_command(self, test_framework: str = "", custom_command: str = "") -> List[str]:
        """Get the test command, preferring custom > framework > default."""
        if custom_command:
            return custom_command.split()
        if test_framework:
            # Could map framework to specific command
            return self.default_test_command
        return self.default_test_command

    def get_build_command(self, custom_command: str = "") -> List[str]:
        """Get the build command, preferring custom > default."""
        if custom_command:
            return custom_command.split()
        return self.build_commands

    def is_test_file(self, file_path: str) -> bool:
        """Check if a file path matches test patterns."""
        import fnmatch
        filename = Path(file_path).name
        for pattern in self.test_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
        return False

    def is_config_file(self, file_path: str) -> bool:
        """Check if a file path is a config file for this language."""
        filename = Path(file_path).name
        return filename in self.config_files


from pathlib import Path