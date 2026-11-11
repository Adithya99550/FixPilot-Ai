"""FixPilot AI JavaScript/TypeScript language configuration."""

from fixpilot.languages.base import LanguageConfig


JAVASCRIPT_CONFIG = LanguageConfig(
    name="javascript",
    extensions=[".js", ".jsx", ".mjs", ".cjs"],
    test_patterns=["test_*.js", "*_test.js", "*.spec.js", "*.test.js", "__tests__/**"],
    config_files=["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts"],
    default_test_command=["npm", "test"],
    build_commands=["npm", "install"],
    sandbox_image="fixpilot-sandbox:node",
    test_frameworks=["jest", "vitest", "mocha", "ava", "tape"],
    language_specific_flags={
        "npm_registry": "--registry",
        "jest_coverage": "--coverage",
        "vitest_coverage": "--coverage",
    },
)


TYPESCRIPT_CONFIG = LanguageConfig(
    name="typescript",
    extensions=[".ts", ".tsx"],
    test_patterns=["test_*.ts", "*_test.ts", "*.spec.ts", "*.test.ts", "__tests__/**"],
    config_files=["package.json", "tsconfig.json", "jest.config.ts", "vitest.config.ts"],
    default_test_command=["npm", "test"],
    build_commands=["npm install", "npm ci", "npm run build"],
    sandbox_image="fixpilot-sandbox:node",
    test_frameworks=["jest", "vitest", "mocha", "ava"],
    language_specific_flags={
        "tsc_no_emit": "--noEmit",
    },
)


def get_javascript_config() -> LanguageConfig:
    """Get the JavaScript language configuration."""
    return JAVASCRIPT_CONFIG


def get_typescript_config() -> LanguageConfig:
    """Get the TypeScript language configuration."""
    return TYPESCRIPT_CONFIG