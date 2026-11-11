"""Pytest configuration for the off_by_one sample project.

The tests import the module under test directly (``from sum_range import
sum_range``). When the suite is started from the repository root the project
directory is not on ``sys.path``, so the import fails. Adding the project
directory here makes the sample work from *both* locations:

    python -m pytest sample_projects/off_by_one/tests -v
    cd sample_projects/off_by_one && python -m pytest tests -v
"""

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
