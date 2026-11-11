"""FixPilot AI Dashboard - Streamlit UI.

A real-time dashboard for monitoring FixPilot self-healing workflows,
inspecting diagnostic evidence, reviewing generated patches, and exporting reports.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from fixpilot.config import get_config
from fixpilot.storage import Storage

# Configure Streamlit page
st.set_page_config(
    page_title="FixPilot AI Dashboard",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    config = get_config()
    db_path = config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3")
    
    if "storage" not in st.session_state:
        st.session_state.storage = Storage(db_path)
    if "current_run" not in st.session_state:
        st.session_state.current_run = None
    if "nav_page" not in st.session_state:
        st.session_state.nav_page = "Home"


def main():
    """Main dashboard application."""
    init_session_state()

    # Sidebar Navigation
    with st.sidebar:
        st.title("✈️ FixPilot AI")
        st.caption("Autonomous Self-Healing Agent")
        st.markdown("---")
        
        pages = ["Home", "Run History", "Run Detail", "Reports"]
        current_idx = pages.index(st.session_state.nav_page) if st.session_state.nav_page in pages else 0
        
        selected_page = st.radio(
            "Navigation",
            pages,
            index=current_idx,
            key="navigation_radio",
        )
        st.session_state.nav_page = selected_page

        st.markdown("---")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()

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
    failed_runs = statuses.count("FAILED")
    pending_runs = statuses.count("PENDING")

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
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No runs recorded yet. Start a run using the CLI to see distribution.")

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

    badge_class = "badge-success" if status == "SUCCESS" else ("badge-failed" if status == "FAILED" else "badge-pending")

    with st.expander(f"{run_id} — {status}"):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Started:** {started}")
            st.write(f"**Mode:** `{mode}`")
        with c2:
            attempts = st.session_state.storage.get_run_attempts(run_id)
            st.write(f"**Total Attempts:** {len(attempts)}")
            st.write(f"**Status:** <span class='status-badge {badge_class}'>{status}</span>", unsafe_allow_html=True)
        
        if st.button("Inspect Details", key=f"inspect_{run_id}"):
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
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True)

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
    with m1:
        st.metric("Status", str(run.get("status", "N/A")).upper())
    with m2:
        st.metric("Mode", run.get("mode", "safe"))
    with m3:
        st.metric("Model", run.get("model_name") or "default")
    with m4:
        st.metric("Started", str(run.get("started_at", "N/A"))[:16])

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

                patch_diff = att.get("patch_path")
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
