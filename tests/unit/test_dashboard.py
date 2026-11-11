"""Tests for the FixPilot dashboard helper logic.

The dashboard itself is a Streamlit script, so only the parts that can be
tested without a running Streamlit runtime are covered here: the command
that starts a run and the environment it runs in.
"""

import importlib.util
import sys
from pathlib import Path

import pytest


DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "dashboard" / "app.py"


@pytest.fixture(scope="module")
def dashboard():
    """Import the dashboard module without running the Streamlit app."""
    if not DASHBOARD_PATH.exists():
        pytest.skip("dashboard/app.py is not present")
    spec = importlib.util.spec_from_file_location("fixpilot_dashboard", DASHBOARD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fixpilot_dashboard"] = module
    spec.loader.exec_module(module)
    return module


class TestRunSessionCommand:
    def test_command_uses_the_cli(self, dashboard, tmp_path: Path):
        session = dashboard.RunSession(project_path=str(tmp_path))
        command = session.build_command()
        assert command[1:4] == ["-m", "fixpilot", "run"]
        assert command[4] == str(tmp_path)

    def test_analysis_only_flag(self, dashboard, tmp_path: Path):
        session = dashboard.RunSession(project_path=str(tmp_path), analysis_only=True)
        assert "--analysis-only" in session.build_command()

    def test_auto_approve_flag(self, dashboard, tmp_path: Path):
        session = dashboard.RunSession(project_path=str(tmp_path), auto_approve=True)
        assert "--yes" in session.build_command()

    def test_no_auto_approve_by_default(self, dashboard, tmp_path: Path):
        session = dashboard.RunSession(project_path=str(tmp_path))
        assert "--yes" not in session.build_command()

    def test_environment_contains_the_source_directory(self, dashboard, tmp_path: Path):
        session = dashboard.RunSession(project_path=str(tmp_path))
        env = session.build_environment()
        assert str(dashboard.SRC_DIR) in env.get("PYTHONPATH", "")

    def test_environment_keeps_the_existing_pythonpath(self, dashboard, tmp_path, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
        session = dashboard.RunSession(project_path=str(tmp_path))
        env = session.build_environment()
        assert "/somewhere/else" in env["PYTHONPATH"]
        assert str(dashboard.SRC_DIR) in env["PYTHONPATH"]


class TestSecurityProperties:
    def test_dashboard_never_imports_the_workflow_engine(self, dashboard):
        """The dashboard must not execute the target code in its own process."""
        source = DASHBOARD_PATH.read_text(encoding="utf-8")
        assert "from fixpilot.workflow" not in source
        assert "import fixpilot.workflow" not in source

    def test_dashboard_does_not_disable_the_sandbox(self, dashboard):
        source = DASHBOARD_PATH.read_text(encoding="utf-8")
        assert "FIXPILOT_ALLOW_LOCAL_RUNNER" not in source
        assert "FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION" not in source

    def test_approval_prompt_is_detected(self, dashboard):
        assert dashboard.APPROVAL_PROMPT in "Approve and apply this patch? [y/N]: "


class TestDashboardRenders:
    """The Streamlit app must render without raising."""

    def _app_test(self):
        streamlit_testing = pytest.importorskip(
            "streamlit.testing.v1", reason="streamlit is not installed"
        )
        return streamlit_testing.AppTest.from_file(
            str(DASHBOARD_PATH), default_timeout=60
        )

    def test_home_page_renders(self):
        app = self._app_test()
        app.run()
        assert not app.exception
        assert [h.value for h in app.header] == ["Overview"]

    def test_navigation_contains_the_new_run_page(self):
        app = self._app_test()
        app.run()
        radio = app.sidebar.radio[0]
        assert "New Run" in radio.options

    def test_new_run_page_renders(self):
        app = self._app_test()
        app.run()
        app.sidebar.radio[0].set_value("New Run").run()
        assert not app.exception
        assert any("New Run" in h.value for h in app.header)

    def test_run_history_page_renders(self):
        app = self._app_test()
        app.run()
        app.sidebar.radio[0].set_value("Run History").run()
        assert not app.exception

    def test_reports_page_renders(self):
        app = self._app_test()
        app.run()
        app.sidebar.radio[0].set_value("Reports").run()
        assert not app.exception
