"""FixPilot AI Dashboard - Streamlit UI.

A real-time dashboard for monitoring FixPilot self-healing workflows,
inspecting diagnostic evidence, reviewing generated patches, and exporting
reports.

Security notes
--------------
The dashboard **never** executes the target project's code inside the
Streamlit process. A run is started as a *subprocess* that uses the very same
CLI (and therefore the very same sandbox policy) as a terminal run:

* the Docker sandbox is the default; the dashboard cannot switch it off
* the local (unsafe) runner is only used when the operator explicitly enabled
  it in the environment
* the interactive patch approval is preserved - the dashboard asks the user
  before a patch is applied and forwards the answer to the CLI
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fixpilot.config import get_config, is_unsafe_local_execution_allowed
from fixpilot.storage import Storage

# Configure Streamlit page
st.set_page_config(
    page_title="FixPilot AI Dashboard",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

#: The prompt the CLI prints before it applies a patch.
APPROVAL_PROMPT = "Approve and apply this patch?"

#: Directory that contains the ``fixpilot`` package (for running the CLI
#: from a checkout, even when the package is not installed).
SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# Custom Styling
st.markdown("""
<style>
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        border: 1px solid #e9ecef;
    }
    .status-badge {
        font-weight: 600;
        padding: 0.2rem 0.6rem;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    .badge-success { background-color: #d4edda; color: #155724; }
    .badge-failed { background-color: #f8d7da; color: #721c24; }
    .badge-pending { background-color: #fff3cd; color: #856404; }
    .badge-running { background-color: #cce5ff; color: #004085; }
</style>
""", unsafe_allow_html=True)


def badge_class(status: str) -> str:
    """Return the CSS class of the status badge for ``status``."""
    status = (status or "").upper()
    if status == "SUCCESS":
        return "badge-success"
    if status in ("FAILED", "REPAIR_FAILED", "PATCH_INVALID", "EXECUTION_FAILED",
                  "TIMEOUT", "REJECTED"):
        return "badge-failed"
    if status == "PENDING":
        return "badge-pending"
    return "badge-running"


def init_session_state():
    """Initialize session state variables."""
    config = get_config()
    db_path = config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3")
    reports_dir = config.get("FIXPILOT_REPORTS_DIR", "reports")

    if "storage" not in st.session_state:
        st.session_state.storage = Storage(db_path, reports_dir=reports_dir)
    if "current_run" not in st.session_state:
        st.session_state.current_run = None
    if "nav_page" not in st.session_state:
        st.session_state.nav_page = "Home"
    if "run_session" not in st.session_state:
        st.session_state.run_session = None
    if "project_path" not in st.session_state:
        st.session_state.project_path = str(Path.cwd())


class RunSession:
    """A FixPilot run started from the dashboard.

    The run happens in a separate process (the FixPilot CLI) so the
    dashboard process never executes the target project's code. The session
    collects the output, watches for the approval prompt and forwards the
    user's decision to the CLI.
    """

    def __init__(self, project_path: str, analysis_only: bool = False,
                 auto_approve: bool = False, timeout_seconds: int = 3600):
        self.project_path = project_path
        self.analysis_only = analysis_only
        self.auto_approve = auto_approve
        self.timeout_seconds = timeout_seconds
        self.lines: List[str] = []
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.returncode: Optional[int] = None
        self.approval_requested = False
        self.approval_answered = False
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    # -- construction --------------------------------------------------
    def build_command(self) -> List[str]:
        """Build the CLI command used for this run."""
        command = [sys.executable, "-m", "fixpilot", "run", self.project_path]
        if self.analysis_only:
            command.append("--analysis-only")
        if self.auto_approve:
            command.append("--yes")
        return command

    def build_environment(self) -> Dict[str, str]:
        """Build the environment of the subprocess.

        ``PYTHONPATH`` is extended with the source directory so the CLI can
        be started from a plain checkout as well.
        """
        env = dict(os.environ)
        if SRC_DIR.is_dir():
            existing = env.get("PYTHONPATH", "")
            parts = [str(SRC_DIR)] + ([existing] if existing else [])
            env["PYTHONPATH"] = os.pathsep.join(parts)
        return env

    def start(self):
        """Start the CLI subprocess."""
        command = self.build_command()
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self.build_environment(),
            cwd=str(Path(self.project_path) if Path(self.project_path).is_dir() else Path.cwd()),
        )
        self._thread = threading.Thread(target=self._read_output, daemon=True)
        self._thread.start()

    def _read_output(self):
        """Read the CLI output until the process exits."""
        assert self._process is not None
        stream = self._process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                with self._lock:
                    self.lines.append(line.rstrip("\n"))
                if APPROVAL_PROMPT in line and not self.approval_answered:
                    with self._lock:
                        self.approval_requested = True
        except (ValueError, OSError):
            pass
        finally:
            self.returncode = self._process.wait()
            self.finished_at = time.time()

    # -- interaction ----------------------------------------------------
    def answer_approval(self, approved: bool):
        """Forward the user's approval decision to the CLI."""
        if self._process is None or self._process.stdin is None:
            return False
        if self.approval_answered:
            return False
        try:
            self._process.stdin.write("y\n" if approved else "n\n")
            self._process.stdin.flush()
        except (OSError, ValueError):
            return False
        self.approval_answered = True
        with self._lock:
            self.approval_requested = False
        return True

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    @property
    def output(self) -> str:
        with self._lock:
            return "\n".join(self.lines)

    def run_id(self) -> Optional[str]:
        """Extract the run id from the CLI output."""
        for line in reversed(self.lines):
            if "FixPilot run " in line and "finished with status" in line:
                return line.split("FixPilot run ", 1)[1].split(" finished", 1)[0].strip()
        return None


def _detect_projects() -> List[str]:
    """Return a list of candidate projects near the working directory."""
    candidates: List[str] = []
    cwd = Path.cwd()
    for name in ("sample_projects", "projects", "repos"):
        folder = cwd / name
        if folder.is_dir():
            for child in sorted(folder.iterdir()):
                if child.is_dir() and child.name not in ("__pycache__", "node_modules"):
                    candidates.append(str(child))
    candidates.append(str(cwd))
    return candidates


def sandbox_status(config: Dict[str, Any]) -> Dict[str, Any]:
    """Describe the current sandbox configuration for the UI."""
    from fixpilot.sandbox.docker_executor import DockerExecutor

    docker_available = DockerExecutor(config).is_available()
    unsafe_local = is_unsafe_local_execution_allowed(config)
    return {
        "docker_available": docker_available,
        "unsafe_local_allowed": unsafe_local,
        "network_allowed": bool(config.get("FIXPILOT_ALLOW_NETWORK", False)),
        "approval_required": bool(config.get("FIXPILOT_APPROVAL_REQUIRED", True)),
    }


def main():
    """Main dashboard application."""
    init_session_state()

    # Sidebar Navigation
    with st.sidebar:
        st.title("✈️ FixPilot AI")
        st.caption("Autonomous Self-Healing Agent")
        st.markdown("---")

        pages = ["Home", "New Run", "Run History", "Run Detail", "Reports"]
        current_idx = pages.index(st.session_state.nav_page) if st.session_state.nav_page in pages else 0

        selected_page = st.radio(
            "Navigation",
            pages,
            index=current_idx,
            key="navigation_radio",
        )
        st.session_state.nav_page = selected_page

        st.markdown("---")
        if st.button("🔄 Refresh Data", width="stretch"):
            st.rerun()

        st.markdown("---")
        with st.expander("🛡️ Sandbox Status"):
            status = sandbox_status(get_config())
            st.write(f"**Docker available:** {'yes' if status['docker_available'] else 'no'}")
            st.write(
                f"**Unsafe local execution:** "
                f"{'ENABLED (target code runs on this host)' if status['unsafe_local_allowed'] else 'disabled'}"
            )
            st.write(f"**Network in sandbox:** {'allowed' if status['network_allowed'] else 'disabled'}")
            st.write(
                f"**Patch approval:** "
                f"{'required' if status['approval_required'] else 'auto-approved'}"
            )
            if not status["docker_available"] and not status["unsafe_local_allowed"]:
                st.warning(
                    "Docker is unavailable and unsafe local execution is "
                    "disabled - a run will be BLOCKED before any project code "
                    "is executed."
                )

        st.markdown("---")
        with st.expander("⚠️ Honest Limitations"):
            st.markdown("""
- **It cannot fix what isn't tested.** No failing test → it reports "nothing to repair."
- **Passing tests don't guarantee correctness** — the fix might be wrong even if tests pass.
- **LLM diagnosis can be wrong or incomplete.**
- **Non-Python languages need Docker** — the sandbox images are mandatory for Go/Rust/Java/JS.
- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).

> **In short:** FixPilot is a **test-driven self-healing agent** — it needs a failing test to work from, and Docker for non-Python languages.
""")

    # Render Active Page
    if st.session_state.nav_page == "Home":
        render_home()
    elif st.session_state.nav_page == "New Run":
        render_new_run()
    elif st.session_state.nav_page == "Run History":
        render_run_history()
    elif st.session_state.nav_page == "Run Detail":
        render_run_detail()
    elif st.session_state.nav_page == "Reports":
        render_reports()


def render_home():
    """Render the dashboard overview home page."""
    st.header("Overview")

    runs = st.session_state.storage.list_runs(limit=100)

    # Calculate Metrics
    total_runs = len(runs)
    statuses = [str(r.get("status", "")).upper() for r in runs]
    successful_runs = statuses.count("SUCCESS")
    failed_runs = len([s for s in statuses if s in ("FAILED", "REPAIR_FAILED",
                                                    "PATCH_INVALID", "EXECUTION_FAILED",
                                                    "TIMEOUT", "REJECTED")])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Runs", total_runs)
    with col2:
        st.metric("Successful Repairs", successful_runs)
    with col3:
        st.metric("Failed Runs", failed_runs)
    with col4:
        rate = round((successful_runs / total_runs * 100), 1) if total_runs > 0 else 0
        st.metric("Success Rate", f"{rate}%")

    st.markdown("---")

    # Chart & Recent Activity
    col_chart, col_recent = st.columns([1, 1])

    with col_chart:
        st.subheader("Outcome Distribution")
        if total_runs > 0:
            labels = ["Success", "Failed", "Other"]
            values = [successful_runs, failed_runs, max(0, total_runs - successful_runs - failed_runs)]

            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=0.45,
                marker=dict(colors=["#28a745", "#dc3545", "#ffc107"]),
            )])
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No runs recorded yet. Start a run to see the distribution.")

    with col_recent:
        st.subheader("Recent Runs")
        if runs:
            recent_runs = runs[:5]
            for run in recent_runs:
                render_run_card(run)
        else:
            st.info("No run history available.")


def render_run_card(run: Dict[str, Any]):
    """Render a clean summary card for a single run."""
    run_id = str(run.get("run_id", "N/A"))
    status = str(run.get("status", "N/A")).upper()
    started = str(run.get("started_at", "N/A"))[:19]
    mode = run.get("mode", "safe")

    with st.expander(f"{run_id} — {status}"):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Started:** {started}")
            st.write(f"**Mode:** `{mode}`")
        with c2:
            attempts = st.session_state.storage.get_run_attempts(run_id)
            st.write(f"**Total Attempts:** {len(attempts)}")
            st.write(
                f"**Status:** <span class='status-badge {badge_class(status)}'>{status}</span>",
                unsafe_allow_html=True,
            )

        if st.button("Inspect Details", key=f"inspect_{run_id}"):
            st.session_state.current_run = run_id
            st.session_state.nav_page = "Run Detail"
            st.rerun()


def render_new_run():
    """Render the page that starts a new FixPilot run."""
    st.header("▶️ New Run")
    st.caption(
        "The run is executed by the FixPilot CLI in a separate process - the "
        "dashboard never runs the target project's code itself."
    )

    status = sandbox_status(get_config())

    # ---- Project selection -------------------------------------------
    st.subheader("1. Project")
    projects = _detect_projects()
    options = list(dict.fromkeys([st.session_state.project_path] + projects))

    mode = st.radio(
        "Select a project",
        ["Enter a path", "Pick a detected project"],
        horizontal=True,
        key="project_select_mode",
    )

    if mode == "Pick a detected project" and options:
        selected = st.selectbox("Detected projects", options, key="project_selectbox")
        st.session_state.project_path = selected
    else:
        typed = st.text_input(
            "Project path",
            value=st.session_state.project_path,
            key="project_path_input",
            help="Absolute or relative path of the project to analyse/repair.",
        )
        if typed:
            st.session_state.project_path = typed

    project_path = Path(st.session_state.project_path).expanduser()
    if project_path.is_dir():
        st.success(f"Target: `{project_path.resolve()}`")
    else:
        st.error(f"'{project_path}' is not a valid directory.")

    # ---- Options ------------------------------------------------------
    st.subheader("2. Options")
    c1, c2 = st.columns(2)
    with c1:
        analysis_only = st.checkbox(
            "Analysis only (no patch is applied)",
            value=False,
            key="analysis_only",
            help="Stop after the investigation stage - nothing is modified.",
        )
    with c2:
        auto_approve = st.checkbox(
            "Auto-approve patches (no human review)",
            value=False,
            key="auto_approve",
            help=(
                "When enabled every proposed patch is applied without asking. "
                "Only use this for projects you trust."
            ),
        )

    if auto_approve:
        st.warning(
            "Auto-approve is enabled: patches will be applied to the "
            "disposable workspace without a human review."
        )

    if not status["docker_available"] and not status["unsafe_local_allowed"]:
        st.error(
            "Docker is unavailable and unsafe local execution is disabled. "
            "The run will be BLOCKED - this is the safe default."
        )

    # ---- Start --------------------------------------------------------
    st.subheader("3. Run")
    col_start, col_stop, _ = st.columns([1, 1, 2])
    with col_start:
        start_clicked = st.button(
            "🚀 Start Run",
            type="primary",
            disabled=not project_path.is_dir(),
            key="start_run",
        )
    with col_stop:
        stop_clicked = st.button("⏹️ Stop", key="stop_run")

    if start_clicked:
        session = RunSession(
            project_path=str(project_path.resolve()),
            analysis_only=analysis_only,
            auto_approve=auto_approve,
        )
        try:
            session.start()
        except OSError as exc:
            st.error(f"Could not start the FixPilot CLI: {exc}")
            session = None
        st.session_state.run_session = session
        st.rerun()

    session: Optional[RunSession] = st.session_state.run_session
    if session is None:
        return

    if stop_clicked and session._process is not None and not session.finished:
        session._process.terminate()
        st.warning("The run was terminated.")

    # ---- Progress -----------------------------------------------------
    st.markdown("---")
    st.subheader("Progress")

    if session.finished:
        st.success(
            f"Run finished with exit code {session.returncode} "
            f"after {round((session.finished_at or time.time()) - session.started_at, 1)}s"
        )
    else:
        st.info("The run is in progress...")

    output = session.output
    if output:
        st.code(output[-20000:], language="console")

    # ---- Approval -----------------------------------------------------
    if session.approval_requested and not session.approval_answered:
        st.warning("The FixPilot CLI is waiting for approval of a proposed patch.")
        col_a, col_r = st.columns(2)
        with col_a:
            if st.button("✅ Approve patch", type="primary", key="approve_patch"):
                session.answer_approval(True)
                st.rerun()
        with col_r:
            if st.button("❌ Reject patch", key="reject_patch"):
                session.answer_approval(False)
                st.rerun()

    # ---- Result -------------------------------------------------------
    run_id = session.run_id()
    if run_id and session.finished:
        st.markdown("---")
        st.subheader("Result")
        run = st.session_state.storage.get_run(run_id)
        if run:
            run_status = str(run.get("status", "N/A")).upper()
            st.write(
                f"**Status:** <span class='status-badge {badge_class(run_status)}'>{run_status}</span>",
                unsafe_allow_html=True,
            )
            if run.get("error_summary"):
                st.error(f"**Error:** {run['error_summary']}")
            if run.get("final_test_status"):
                st.write(f"**Final test status:** `{run.get('final_test_status')}`")
            st.write(f"**Attempts:** {run.get('attempt_count', 0)}")

            attempts = st.session_state.storage.get_run_attempts(run_id)
            if attempts:
                st.dataframe(pd.DataFrame([
                    {
                        "Attempt": a.get("attempt_number"),
                        "Verification": a.get("verification_status"),
                        "Tests": a.get("test_status"),
                        "Approval": a.get("approval_status"),
                        "Patch": a.get("patch_summary"),
                    }
                    for a in attempts
                ]), width="stretch")

        if st.button("Open Run Details", key="open_run_details"):
            st.session_state.current_run = run_id
            st.session_state.nav_page = "Run Detail"
            st.rerun()


def render_run_history():
    """Render the full searchable run history table."""
    st.header("Run History")

    runs = st.session_state.storage.list_runs(limit=50)
    if not runs:
        st.info("No runs recorded yet.")
        return

    table_data = []
    for r in runs:
        r_id = r.get("run_id", "N/A")
        attempts = st.session_state.storage.get_run_attempts(r_id)
        table_data.append({
            "Run ID": r_id,
            "Status": str(r.get("status", "N/A")).upper(),
            "Started At": str(r.get("started_at", "N/A"))[:19],
            "Mode": r.get("mode", "safe"),
            "Attempts": len(attempts),
            "Final Test": r.get("final_test_status") or "N/A",
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, width="stretch")

    st.markdown("---")
    st.subheader("Select a Run for Deep Inspection")
    run_ids = [r["Run ID"] for r in table_data]
    selected = st.selectbox("Run ID", run_ids, index=0 if run_ids else None)

    if selected and st.button("View Run Details", type="primary"):
        st.session_state.current_run = selected
        st.session_state.nav_page = "Run Detail"
        st.rerun()


def render_run_detail():
    """Render deep attempt inspection for the selected run."""
    st.header("Run Detail")

    run_id = st.session_state.get("current_run")
    if not run_id:
        st.warning("No run selected. Please pick a run from Run History.")
        if st.button("Go to Run History"):
            st.session_state.nav_page = "Run History"
            st.rerun()
        return

    run = st.session_state.storage.get_run(run_id)
    if not run:
        st.error(f"Run '{run_id}' not found.")
        return

    # Metadata Grid
    st.subheader(f"Metadata: `{run_id}`")
    m1, m2, m3, m4 = st.columns(4)
    run_status = str(run.get("status", "N/A")).upper()
    with m1:
        st.metric("Status", run_status)
    with m2:
        st.metric("Mode", run.get("mode", "safe"))
    with m3:
        st.metric("Model", run.get("model_name") or "default")
    with m4:
        st.metric("Started", str(run.get("started_at", "N/A"))[:16])

    # Errors
    if run.get("error_summary"):
        st.error(f"**Error:** {run['error_summary']}")

    # Final test result
    if run.get("final_test_status"):
        st.markdown("---")
        st.subheader("Final Test Result")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Status:** `{run.get('final_test_status')}`")
            st.write(f"**Exit code:** `{run.get('final_test_exit_code')}`")
        with c2:
            st.write(f"**Attempts:** `{run.get('attempt_count', 0)}`")
        if run.get("final_test_output"):
            with st.expander("Test output"):
                st.code(str(run["final_test_output"])[-8000:], language="console")

    # Attempts Timeline
    st.markdown("---")
    st.subheader("Attempt Timeline")
    attempts = st.session_state.storage.get_run_attempts(run_id)

    if not attempts:
        st.info("No attempts recorded for this run (e.g. baseline passed or halted during analysis).")
    else:
        for att in attempts:
            num = att.get("attempt_number", 1)
            v_status = str(att.get("verification_status", "N/A")).upper()
            t_status = str(att.get("test_status", "N/A")).upper()
            patch_summary = att.get("patch_summary", "None")
            root_cause = att.get("root_cause_summary", "Not recorded")

            with st.expander(f"Attempt #{num} — Verification: {v_status}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Test Suite Result:** `{t_status}`")
                    st.write(f"**Approval Status:** `{att.get('approval_status', 'N/A')}`")
                with c2:
                    st.write(f"**Root Cause:** {root_cause}")
                    st.write(f"**Patch Summary:** {patch_summary}")

                patch_diff = att.get("patch_diff") or att.get("patch_path")
                if patch_diff:
                    st.write("**Patch Diff:**")
                    st.code(patch_diff, language="diff")

    # Export Section
    st.markdown("---")
    st.subheader("Export Report")
    report_content = st.session_state.storage.export_report(run_id) or ""

    st.download_button(
        label="📥 Download Markdown Report",
        data=report_content,
        file_name=f"fixpilot_report_{run_id}.md",
        mime="text/markdown",
        type="primary",
    )


def render_reports():
    """Render live preview and download of generated Markdown reports."""
    st.header("Audit Reports")

    runs = st.session_state.storage.list_runs(limit=20)
    if not runs:
        st.info("No runs available for reporting.")
        return

    run_options = {f"{r.get('run_id')} ({r.get('status')})": r.get('run_id') for r in runs}
    selected_label = st.selectbox("Select Run", list(run_options.keys()))
    selected_run_id = run_options[selected_label]

    report = st.session_state.storage.export_report(selected_run_id)
    if report:
        st.download_button(
            label="📥 Download This Report",
            data=report,
            file_name=f"fixpilot_report_{selected_run_id}.md",
            mime="text/markdown",
        )
        st.markdown("---")
        st.markdown(report)
    else:
        st.warning("No report available for this run.")


if __name__ == "__main__":
    main()
