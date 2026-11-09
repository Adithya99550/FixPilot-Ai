"""FixPilot AI Dashboard - Streamlit UI.

A minimal dashboard for monitoring FixPilot repair workflows.
This is a post-MVP feature that demonstrates the core workflow
without duplicating the CLI logic.

Depends on: streamlit, fixpilot storage, fixpilot agents
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# FixPilot imports
from fixpilot.storage import Storage, Database
from fixpilot.agents.investigator import Investigator
from fixpilot.agents.repairer import Repairer
from fixpilot.agents.verifier import Verifier

# Page config
st.set_page_config(
    page_title="FixPilot AI Dashboard",
    page_icon="🔧",
    layout="wide",
)

# Custom CSS
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .stButton > button {
        width: 100%;
    }
    .status-pass { color: green; }
    .status-fail { color: red; }
    .status-retry { color: orange; }
    .status-stop { color: gray; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if "storage" not in st.session_state:
        st.session_state.storage = Storage()
    if "current_run" not in st.session_state:
        st.session_state.current_run = None
    if "login" not in st.session_state:
        st.session_state.login = False


def login_form():
    """Show login form (placeholder - no real auth in MVP)."""
    st.title("FixPilot AI - Login")
    st.info("This is a demo MVP - no authentication required")
    if st.button("Continue as Guest"):
        st.session_state.login = True
        st.rerun()


def render_run_card(run: dict):
    """Render a run summary card."""
    with st.expander(f"Run {run.get('run_id', 'N/A')[:8]}... - {run.get('status', 'N/A').upper()}"):
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"Started: {run.get('started_at', 'N/A')}")
        with col2:
            st.caption(f"Finished: {run.get('finished_at', 'N/A')}")
        
        st.write(f"**Status:** {run.get('status', 'N/A').upper()}")
        st.write(f"**Mode:** {run.get('mode', 'N/A')}")
        st.write(f"**Model:** {run.get('model_name', 'N/A')}")
        
        # Show attempt count if available
        attempts = st.session_state.storage.get_run_attempts(run.get('run_id', ''))
        if attempts:
            st.write(f"**Attempts:** {len(attempts)}")


def render_report(report_md: str):
    """Render a Markdown report."""
    if report_md:
        st.markdown(report_md)
    else:
        st.info("No report available for this run")


def main():
    """Dashboard main entry point."""
    init_session_state()
    
    if not st.session_state.login:
        login_form()
        return
    
    st.title("FixPilot AI Dashboard")
    st.caption("Autonomous Software Debugging and Self-Healing Agent")
    
    # Sidebar
    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Go to", ["Home", "Run History", "Run Detail", "Reports"])
        
        if st.button("Refresh Data"):
            st.rerun()
        
        if st.button("Logout"):
            st.session_state.login = False
            st.rerun()
    
    # Main content
    if page == "Home":
        render_home()
    elif page == "Run History":
        render_run_history()
    elif page == "Run Detail":
        render_run_detail()
    elif page == "Reports":
        render_reports()


def render_home():
    """Render the home page."""
    st.header("Welcome to FixPilot AI")
    
    st.markdown("""
    **FixPilot AI** is an autonomous software debugging and self-healing agent.
    
    The core CLI workflow is complete and verified. This dashboard provides
    a basic interface for viewing run history and reports.
    """)
    
    # Quick stats
    runs = st.session_state.storage.list_runs(limit=5)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Runs", len(runs))
    with col2:
        statuses = [r.get('status', '') for r in runs]
        passed = statuses.count('success') if statuses else 0
        st.metric("Successful Repairs", passed)
    with col3:
        failed = statuses.count('failed') if statuses else 0
        st.metric("Failed Repairs", failed)
    
    if runs:
        st.subheader("Recent Runs")
        for run in runs:
            render_run_card(run)
    else:
        st.info("No runs found. Start a new run using the CLI.")


def render_run_history():
    """Render the run history page."""
    st.header("Run History")
    
    runs = st.session_state.storage.list_runs(limit=20)
    
    if not runs:
        st.info("No runs found.")
        return
    
    # Create a DataFrame for display
    df_data = []
    for run in runs:
        attempts = st.session_state.storage.get_run_attempts(run.get('run_id', ''))
        status = run.get('status', 'N/A')
        df_data.append({
            "Run ID": run.get('run_id', '')[:8] + "...",
            "Status": status.upper(),
            "Started": run.get('started_at', 'N/A')[:16] if run.get('started_at') else 'N/A',
            "Attempts": len(attempts),
        })
    
    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True)
    
    # Run selection
    run_ids = [r.get('run_id', '') for r in runs]
    selected_run = st.selectbox("Select a run to view details", run_ids)
    
    if selected_run and st.button("View Details"):
        st.session_state.current_run = selected_run
        st.rerun()


def render_run_detail():
    """Render the run detail page."""
    st.header("Run Details")
    
    run_id = st.session_state.get("current_run", "")
    if not run_id:
        st.info("No run selected. Go to Run History first.")
        return
    
    run = st.session_state.storage.get_run(run_id)
    if not run:
        st.error("Run not found.")
        return
    
    # Render run info
    render_run_card(run)
    
    # Attempts detail
    st.subheader("Attempt History")
    attempts = st.session_state.storage.get_run_attempts(run_id)
    
    for attempt in attempts:
        with st.expander(f"Attempt {attempt.get('attempt_number', 'N/A')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Test Status:** {attempt.get('test_status', 'N/A')}")
                st.write(f"**Verification:** {attempt.get('verification_status', 'N/A')}")
            with col2:
                st.write(f"**Approval:** {attempt.get('approval_status', 'N/A')}")
                st.write(f"**Patch Summary:** {attempt.get('patch_summary', 'N/A')[:80]}...")
    
    # Export report
    if st.button("Export Markdown Report"):
        report = st.session_state.storage.export_report(run_id)
        if report:
            st.download_button(
                label="Download Report",
                data=report,
                file_name=f"fixpilot_report_{run_id}.md",
                mime="text/markdown",
            )


def render_reports():
    """Render the reports page."""
    st.header("Reports")
    
    runs = st.session_state.storage.list_runs(limit=10)
    
    if not runs:
        st.info("No runs found.")
        return
    
    run_ids = [r.get('run_id', '') for r in runs]
    selected_run = st.selectbox("Select a run to view report", run_ids)
    
    if selected_run:
        report = st.session_state.storage.export_report(selected_run)
        if report:
            st.markdown(report)
        
        if st.button("Download Report"):
            st.download_button(
                label="Download Report",
                data=report or "",
                file_name=f"fixpilot_report_{selected_run}.md",
                mime="text/markdown",
            )


if __name__ == "__main__":
    main()