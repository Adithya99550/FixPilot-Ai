"""FixPilot AI Go language configuration."""

from fixpilot.languages.base import LanguageConfig


GO_CONFIG = LanguageConfig(
    name="go",
    extensions=[".go"],
    test_patterns=["*_test.go"],
    config_files=["go.mod", "go.sum", "go.work"],
    default_test_command=["go", "test", "./..."],
    build_commands=["sh", "-c", "go mod download && go build ./..."],
    sandbox_image="fixpilot-sandbox:go",
    test_frameworks=["go test", "testify", "ginkgo", "goconvey"],
    language_specific_flags={
        "go_race": "-race",
        "go_cover": "-cover",
        "go_verbose": "-v",
        "go_count": "-count",
    },
)


def get_config() -> LanguageConfig:
    """Get the Go language configuration."""
    return GO_CONFIG