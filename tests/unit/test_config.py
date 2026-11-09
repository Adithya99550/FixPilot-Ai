"""Unit tests for FixPilot AI configuration."""

import pytest
from unittest.mock import patch, MagicMock

from fixpilot.config import get_config


class TestGetConfig:
    """Test configuration loading."""

    def test_default_values(self):
        """Test that default config values are set."""
        config = get_config()
        assert "GEMINI_API_KEY" in config
        assert "FIXPILOT_MODEL" in config
        assert "FIXPILOT_LOG_LEVEL" in config
        assert "FIXPILOT_DB_PATH" in config
        assert "FIXPILOT_SANDBOX_IMAGE" in config
        assert "FIXPILOT_MAX_RETRIES" in config
        assert "FIXPILOT_TIMEOUT_SECONDS" in config
        assert "FIXPILOT_APPROVAL_REQUIRED" in config

    def test_custom_values(self):
        """Test custom environment variables."""
        env = {
            "GEMINI_API_KEY": "test_key_12345",
            "FIXPILOT_MODEL": "gemini-1.5-pro",
            "FIXPILOT_LOG_LEVEL": "DEBUG",
            "FIXPILOT_DB_PATH": "custom.db",
            "FIXPILOT_SANDBOX_IMAGE": "custom-sandbox:tag",
            "FIXPILOT_MAX_RETRIES": "5",
            "FIXPILOT_TIMEOUT_SECONDS": "300",
            "FIXPILOT_APPROVAL_REQUIRED": "false",
        }
        with patch.dict("os.environ", env, clear=False):
            config = get_config()
            assert config["GEMINI_API_KEY"] == "test_key_12345"
            assert config["FIXPILOT_MODEL"] == "gemini-1.5-pro"
            assert config["FIXPILOT_LOG_LEVEL"] == "DEBUG"
            assert config["FIXPILOT_DB_PATH"] == "custom.db"
            assert config["FIXPILOT_SANDBOX_IMAGE"] == "custom-sandbox:tag"
            assert config["FIXPILOT_MAX_RETRIES"] == 5
            assert config["FIXPILOT_TIMEOUT_SECONDS"] == 300
            assert config["FIXPILOT_APPROVAL_REQUIRED"] == False