"""FixPilot AI state schema."""

from pydantic import BaseModel, Field


class FixPilotState(BaseModel):
    """Typed state schema for FixPilot workflow."""
    run_id: str = Field(default="", description="Unique run identifier")
    target_path: str = Field(default="", description="Target project path")
    workspace_path: str = Field(default="", description="Disposable workspace path")
    project_metadata: dict = Field(default_factory=dict, description="Project metadata")
    test_command: str = Field(default="python -m pytest -q", description="Test command")
    baseline_result: dict = Field(default_factory=dict, description="Baseline test result")
    diagnostics: dict = Field(default_factory=dict, description="Collected diagnostics")
    investigation: dict = Field(default_factory=dict, description="Investigation result")
    repair_plan: dict = Field(default_factory=dict, description="Repair plan")
    patch_text: str = Field(default="", description="Generated patch unified diff")
    patch_validation: dict = Field(default_factory=dict, description="Patch validation result")
    approval_status: str = Field(default="pending", description="Approval status")
    applied_patch_id: str = Field(default="", description="Applied patch identifier")
    post_patch_result: dict = Field(default_factory=dict, description="Post-patch test result")
    verification: dict = Field(default_factory=dict, description="Verification result")
    retry_count: int = Field(default=0, description="Retry count")
    max_retries: int = Field(default=2, description="Maximum retries")
    stage: str = Field(default="INITIALIZE", description="Current workflow stage")
    status: str = Field(default="PENDING", description="Run status")
    error: str = Field(default="", description="Error message if any")
    report_path: str = Field(default="", description="Report file path")
    started_at: str = Field(default="", description="Run start timestamp")
    finished_at: str = Field(default="", description="Run finish timestamp")
    # Multi-language support
    language: str = Field(default="", description="Programming language (python, javascript, go, rust, java)")
    test_framework: str = Field(default="", description="Test framework (pytest, jest, go test, cargo test, junit)")
    build_command: str = Field(default="", description="Build command to run before tests")
    repo_url: str = Field(default="", description="GitHub repository URL")
    branch: str = Field(default="", description="Git branch to checkout")
    commit: str = Field(default="", description="Git commit SHA to checkout")
    github_token: str = Field(default="", description="GitHub token for private repos")