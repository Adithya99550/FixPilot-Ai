"""FixPilot AI Python language configuration."""

from fixpilot.languages.base import LanguageConfig


PYTHON_CONFIG = LanguageConfig(
    name="python",
    extensions=[".py"],
    test_patterns=["test_*.py", "*_test.py", "conftest.py"],
    config_files=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-dev.txt", "tox.ini", "pytest.ini"],
    default_test_command=["python", "-m", "pytest", "-q"],
    build_commands=[],
    sandbox_image="fixpilot-sandbox:python",
    test_frameworks=["pytest", "unittest", "nose2"],
    language_specific_flags={
        "pytest_verbose": "-v",
        "pytest_cov": "--cov",
        "pip_index": "--index-url",
    },
)


def get_config() -> LanguageConfig:
    """Get the Python language configuration."""
    return PYTHON_CONFIG