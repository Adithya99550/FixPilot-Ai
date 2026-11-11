"""FixPilot AI execution schema."""

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """Structured execution result."""
    exit_code: int = Field(default=0, description="Process exit code")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    timed_out: bool = Field(default=False, description="Whether execution timed out")
    duration: float = Field(default=0.0, description="Execution duration in seconds")
    sandbox_id: str = Field(default="", description="Sandbox execution ID")


class RunStatus:
    """Canonical workflow run statuses.

    The status is always derived from the *actual* outcome of the run: a run
    is only ``SUCCESS`` when the verification step really confirmed that the
    tests pass.
    """

    #: Repair verified - the failing tests now pass.
    SUCCESS = "SUCCESS"
    #: The run finished without repairing the problem.
    FAILED = "FAILED"
    #: Some previously failing tests now pass, but others still fail.
    PARTIAL = "PARTIAL"
    #: The run was cancelled by the user (Ctrl+C).
    CANCELLED = "CANCELLED"
    #: A test run or the workflow exceeded its time limit.
    TIMEOUT = "TIMEOUT"
    #: No repair patch could be generated (LLM missing / failed / invalid).
    REPAIR_FAILED = "REPAIR_FAILED"
    #: A generated patch was rejected by the validator.
    PATCH_INVALID = "PATCH_INVALID"
    #: The test command could not be executed at all.
    EXECUTION_FAILED = "EXECUTION_FAILED"
    #: The user rejected the proposed patch.
    REJECTED = "REJECTED"
    #: The project has no tests - there was nothing to repair or verify.
    NO_TESTS = "NO_TESTS"

    ALL = (
        SUCCESS,
        FAILED,
        PARTIAL,
        CANCELLED,
        TIMEOUT,
        REPAIR_FAILED,
        PATCH_INVALID,
        EXECUTION_FAILED,
        REJECTED,
        NO_TESTS,
    )

    @classmethod
    def is_terminal_success(cls, status: str) -> bool:
        """Return True when the status means the repair was verified."""
        return status == cls.SUCCESS
