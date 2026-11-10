"""FixPilot AI configuration management."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def get_config():
    """Get configuration as dictionary."""
    return {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "FIXPILOT_MODEL": os.getenv("FIXPILOT_MODEL", "gemini-1.5-flash"),
        "FIXPILOT_LOG_LEVEL": os.getenv("FIXPILOT_LOG_LEVEL", "INFO"),
        "FIXPILOT_DB_PATH": os.getenv("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"),
        "FIXPILOT_SANDBOX_IMAGE": os.getenv("FIXPILOT_SANDBOX_IMAGE", "fixpilot-sandbox:latest"),
        "FIXPILOT_MAX_RETRIES": int(os.getenv("FIXPILOT_MAX_RETRIES", "2")),
        "FIXPILOT_TIMEOUT_SECONDS": int(os.getenv("FIXPILOT_TIMEOUT_SECONDS", "120")),
        "FIXPILOT_APPROVAL_REQUIRED": os.getenv("FIXPILOT_APPROVAL_REQUIRED", "true").lower() == "true",
        "FIXPILOT_ANALYSIS_ONLY": os.getenv("FIXPILOT_ANALYSIS_ONLY", "false").lower() == "true",
        "FIXPILOT_REPORTS_DIR": os.getenv("FIXPILOT_REPORTS_DIR", "reports"),
        "PROJECT_ROOT": str(PROJECT_ROOT),
    }