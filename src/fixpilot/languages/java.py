"""FixPilot AI Java language configuration."""

from fixpilot.languages.base import LanguageConfig


JAVA_MAVEN_CONFIG = LanguageConfig(
    name="java-maven",
    extensions=[".java"],
    test_patterns=["*Test.java", "*Tests.java", "*TestCase.java"],
    config_files=["pom.xml", "mvnw", "mvnw.cmd"],
    default_test_command=["mvn", "test"],
    build_commands=["mvn", "test-compile"],
    sandbox_image="fixpilot-sandbox:java",
    test_frameworks=["junit4", "junit5", "testng", "mockito"],
    language_specific_flags={
        "maven_surefire": "-Dtest",
        "maven_failsafe": "-Dit.test",
        "maven_skip_tests": "-DskipTests",
    },
    needs_network=True,  # Maven needs network to download dependencies
)


JAVA_GRADLE_CONFIG = LanguageConfig(
    name="java-gradle",
    extensions=[".java", ".kt"],
    test_patterns=["*Test.java", "*Tests.java", "*TestCase.java", "*Test.kt", "*Tests.kt"],
    config_files=["build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradlew", "gradlew.bat"],
    default_test_command=["./gradlew", "test"],
    build_commands=["./gradlew", "compileJava", "compileTestJava"],
    sandbox_image="fixpilot-sandbox:java-gradle",
    test_frameworks=["junit4", "junit5", "testng", "mockito", "spock"],
    language_specific_flags={
        "gradle_tests": "--tests",
        "gradle_continuous": "--continuous",
        "gradle_no_daemon": "--no-daemon",
    },
)


def get_maven_config() -> LanguageConfig:
    """Get the Java Maven language configuration."""
    return JAVA_MAVEN_CONFIG


def get_gradle_config() -> LanguageConfig:
    """Get the Java Gradle language configuration."""
    return JAVA_GRADLE_CONFIG


def get_java_config(build_tool: str = "maven") -> LanguageConfig:
    """Get the Java language configuration based on build tool."""
    if build_tool.lower() == "gradle":
        return JAVA_GRADLE_CONFIG
    return JAVA_MAVEN_CONFIG