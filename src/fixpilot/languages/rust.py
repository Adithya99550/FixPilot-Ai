"""FixPilot AI Rust language configuration."""

from fixpilot.languages.base import LanguageConfig


RUST_CONFIG = LanguageConfig(
    name="rust",
    extensions=[".rs"],
    test_patterns=["*_test.rs", "tests/*.rs"],
    config_files=["Cargo.toml", "Cargo.lock"],
    default_test_command=["cargo", "test"],
    build_commands=["cargo", "build"],
    sandbox_image="fixpilot-sandbox:rust",
    test_frameworks=["cargo test", "proptest", "quickcheck"],
    language_specific_flags={
        "cargo_release": "--release",
        "cargo_all_features": "--all-features",
        "cargo_no_fail_fast": "--no-fail-fast",
    },
)


def get_config() -> LanguageConfig:
    """Get the Rust language configuration."""
    return RUST_CONFIG