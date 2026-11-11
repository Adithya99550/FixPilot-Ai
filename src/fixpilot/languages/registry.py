"""FixPilot AI language registry.

Provides language detection and configuration lookup.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fixpilot.languages.base import LanguageConfig
from fixpilot.languages.python import get_config as get_python_config
from fixpilot.languages.javascript import get_javascript_config, get_typescript_config
from fixpilot.languages.go import get_config as get_go_config
from fixpilot.languages.rust import get_config as get_rust_config
from fixpilot.languages.java import get_maven_config, get_gradle_config, get_java_config


# Registry of all language configurations
LANGUAGE_CONFIGS: Dict[str, LanguageConfig] = {
    "python": get_python_config(),
    "javascript": get_javascript_config(),
    "typescript": get_typescript_config(),
    "go": get_go_config(),
    "rust": get_rust_config(),
    "java-maven": get_maven_config(),
    "java-gradle": get_gradle_config(),
}

# Aliases for common names
LANGUAGE_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "java": "java-maven",
    "maven": "java-maven",
    "gradle": "java-gradle",
}


def get_language_config(language: str) -> Optional[LanguageConfig]:
    """Get a language configuration by name or alias.

    Args:
        language: Language name or alias (e.g., 'python', 'py', 'javascript')

    Returns:
        LanguageConfig if found, None otherwise.
    """
    normalized = language.lower().strip()
    # Check aliases first
    if normalized in LANGUAGE_ALIASES:
        normalized = LANGUAGE_ALIASES[normalized]
    return LANGUAGE_CONFIGS.get(normalized)


def detect_language(project_path: Path) -> Optional[str]:
    """Detect the primary language of a project by examining files.

    Args:
        project_path: Path to the project root.

    Returns:
        Language identifier (e.g., 'python', 'javascript') or None if undetected.
    """
    if not project_path.is_dir():
        return None

    # Check for config files that strongly indicate a language
    config_indicators: List[Tuple[str, str]] = [
        # (config_file, language)
        ("pyproject.toml", "python"),
        ("setup.py", "python"),
        ("requirements.txt", "python"),
        ("package.json", "javascript"),  # Could be TS too, check further
        ("Cargo.toml", "rust"),
        ("go.mod", "go"),
        ("pom.xml", "java-maven"),
        ("build.gradle", "java-gradle"),
        ("build.gradle.kts", "java-gradle"),
        ("settings.gradle", "java-gradle"),
        ("settings.gradle.kts", "java-gradle"),
    ]

    # First pass: config files
    for config_file, language in config_indicators:
        if (project_path / config_file).exists():
            # Special handling for package.json - check for TypeScript
            if config_file == "package.json":
                return _detect_js_variant(project_path)
            return language

    # Second pass: source file extensions
    extension_counts: Dict[str, int] = {}
    try:
        for entry in project_path.rglob("*"):
            if entry.is_file() and not _is_excluded(entry):
                ext = entry.suffix.lower()
                if ext in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt"}:
                    extension_counts[ext] = extension_counts.get(ext, 0) + 1
    except (OSError, PermissionError):
        pass

    if not extension_counts:
        return None

    # Map extensions to languages
    ext_to_lang = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java-maven",
        ".kt": "java-gradle",
    }

    lang_counts: Dict[str, int] = {}
    for ext, count in extension_counts.items():
        if ext in ext_to_lang:
            lang = ext_to_lang[ext]
            lang_counts[lang] = lang_counts.get(lang, 0) + count

    if not lang_counts:
        return None

    # Return the language with the most files
    return max(lang_counts.items(), key=lambda x: x[1])[0]


def _detect_js_variant(project_path: Path) -> str:
    """Detect if a package.json project is JavaScript or TypeScript."""
    ts_indicators = [
        "tsconfig.json",
        "jest.config.ts",
        "vitest.config.ts",
    ]
    for indicator in ts_indicators:
        if (project_path / indicator).exists():
            return "typescript"

    # Check package.json for TypeScript dependencies
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        try:
            import json
            with open(pkg_json, "r") as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "typescript" in deps or "@types/node" in deps:
                return "typescript"
        except (json.JSONDecodeError, OSError):
            pass

    return "javascript"


def _is_excluded(path: Path) -> bool:
    """Check if a path should be excluded from detection."""
    exclude_dirs = {
        ".git", ".venv", "venv", "env", ".env", "node_modules",
        "__pycache__", "build", "dist", "target", ".pytest_cache",
        ".mypy_cache", ".idea", ".vscode", ".gradle"
    }
    exclude_patterns = {
        ".min.js", ".bundle.js", ".map", ".d.ts",
    }

    for part in path.parts:
        if part in exclude_dirs:
            return True

    for pattern in exclude_patterns:
        if path.name.endswith(pattern):
            return True

    return False


def list_supported_languages() -> List[str]:
    """List all supported language identifiers."""
    return sorted(LANGUAGE_CONFIGS.keys())


def detect_test_framework(project_path: Path, language: str) -> Optional[str]:
    """Detect the test framework used in a project.

    Args:
        project_path: Path to the project root.
        language: Detected language identifier.

    Returns:
        Test framework name or None if undetected.
    """
    config = get_language_config(language)
    if not config:
        return None

    # Check for framework-specific config files
    framework_indicators = {
        "python": {
            "pytest": ["pytest.ini", "pyproject.toml"],  # pyproject.toml checked for [tool.pytest]
            "unittest": [],  # Standard library, no config
        },
        "javascript": {
            "jest": ["jest.config.js", "jest.config.ts", "jest.config.json"],
            "vitest": ["vitest.config.js", "vitest.config.ts"],
            "mocha": [".mocharc.js", ".mocharc.json", "mocha.opts"],
            "ava": ["ava.config.js", "package.json"],  # Check package.json for ava
        },
        "typescript": {
            "jest": ["jest.config.ts", "jest.config.js"],
            "vitest": ["vitest.config.ts", "vitest.config.js"],
        },
        "go": {
            "go test": [],  # Standard library
            "testify": [],  # Just import
            "ginkgo": ["ginkgo.yml", ".github/workflows/ginkgo.yml"],
        },
        "rust": {
            "cargo test": [],  # Standard
        },
        "java-maven": {
            "junit4": [],  # Check pom.xml
            "junit5": [],  # Check pom.xml
            "testng": [],  # Check pom.xml
        },
        "java-gradle": {
            "junit4": [],  # Check build.gradle
            "junit5": [],  # Check build.gradle
            "testng": [],  # Check build.gradle
            "spock": [],  # Check build.gradle
        },
    }

    if language not in framework_indicators:
        return config.test_frameworks[0] if config.test_frameworks else None

    indicators = framework_indicators[language]

    for framework, files in indicators.items():
        for file in files:
            if (project_path / file).exists():
                return framework

        # Special checks for files that need content inspection
        if language in {"python"} and "pyproject.toml" in files:
            pyproject = project_path / "pyproject.toml"
            if pyproject.exists():
                try:
                    with open(pyproject, "r") as f:
                        content = f.read()
                    if "pytest" in content.lower() or "[tool.pytest" in content:
                        return "pytest"
                except (OSError, UnicodeDecodeError):
                    pass

    # Return default framework for the language
    return config.test_frameworks[0] if config.test_frameworks else None