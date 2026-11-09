"""FixPilot AI logging configuration."""

import logging
import sys


def setup_logging(level: str = "INFO"):
    """Set up FixPilot AI logging."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("fixpilot")