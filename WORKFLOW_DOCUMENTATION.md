# FixPilot AI: Workflow Documentation

## Overview

FixPilot AI is an **autonomous software debugging and self-healing agent** that automates the full debugging loop: from scanning a Python project and detecting failing tests, through root-cause investigation, repair planning, patch generation, verification, and reporting.

The system is designed to preserve user control, traceability, and safety while automating repetitive debugging tasks.

---

## Architecture

The system follows a **state-machine workflow** through these stages:

```
INITIALIZE → SCAN_PROJECT → BASELINE_TEST → COLLECT_DIAGNOSTICS → INVESTIGATE → PLAN_REPAIR → GENERATE_PATCH → VALIDATE_PATCH → AWAIT_APPROVAL → APPLY_PATCH → POST_PATCH_TEST → VERIFY → RETRY_DECISION → FINALIZE_REPORT
```

---

## Core Components

### 1. CLI (`src/fixpilot/cli.py`)

Entry point with the following commands:

| Command | Description |
|---------|-------------|
| `fixpilot version` | Display FixPilot version |
| `fixpilot doctor` | Check environment and configuration |
| `fixpilot scan <path>` | Scan a Python project |
| `fixpilot run <path>` | Run the full repair workflow |
| `fixpilot run <path> --analysis-only` | Analysis mode, no patch application |
| `fixpilot run <path> --yes` | Auto-approve patches without interactive prompt |
| `fixpilot history` | List run history |
| `fixpilot show <run-id>` | Show run details |
| `fixpilot export <run-id>` | Export run report |

### 2. Configuration (`src/fixpilot/config.py`)

Loads from `.env` file at project root. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `FIXPILOT_MODEL` | `gemini-1.5-flash` | LLM model to use |
| `FIXPILOT_LOG_LEVEL` | `INFO` | Logging level |
| `FIXPILOT_DB_PATH` | `artifacts/fixpilot.sqlite3` | Database path |
| `FIXPILOT_SANDBOX_IMAGE` | `fixpilot-sandbox:latest` | Docker sandbox image |
| `FIXPILOT_MAX_RETRIES` | `2` | Max repair attempts |
| `FIXPILOT_TIMEOUT_SECONDS` | `120` | Test timeout |
| `FIXPILOT_APPROVAL_REQUIRED` | `true` | Require human approval for patches |
| `FIXPILOT_ANALYSIS_ONLY` | `false` | Analysis-only mode |

### 3. Workflow Engine (`src/fixpilot/workflow/engine.py`)

Orchestrates the full lifecycle:

- **Project scanning** - Detects Python project structure and test files
- **Baseline testing** - Runs initial test suite to identify failures
- **Diagnostics collection** - Captures test output, tracebacks, stderr
- **Investigation** - LLM-powered root cause analysis
- **Planning** - Creates structured repair plans
- **Patch generation** - Generates minimal unified diff patches
- **Patch validation** - Safety checks before application
- **Approval gate** - Interactive or auto-approval for patch application
- **Patch application** - Applies patches to disposable workspace
- **Post-patch testing** - Reruns tests to verify fix
- **Verification** - Compares pre/post patch results
- **Retry management** - Bounded retry with rollback (max 2 attempts)
- **Report generation** - Markdown reports

### 4. Project Scanner (`src/fixpilot/scanner/project_scanner.py`)

Responsibilities:

- Validate target path
- Identify Python project structure
- Detect Git repository and working-tree state
- Detect test configuration (pytest, etc.)
- Identify test files using safe discovery
- Read relevant source files within configured limits
- Exclude secrets, binary files, generated files, caches, and oversized files

**Exclusion patterns** (directories & files): `.git`, `.venv`, `venv`, `.env`, `node_modules`, `__pycache__`, `build`, `dist`, `*.egg-info`, `.pytest_cache`, `.mypy_cache`

**Excluded extensions**: `.pyc`, `.pyo`, `.pyd`, `.so`, `.dll`, `.exe`, `.dat`, `.bin`, `.gz`, `.zip`, `.tar`, `.rar`, `.pdf`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.wmv`, `.avi`, `.mov`, `.mp4`, `.mp3`, `.wav`, `.ogg`, `.flac`

### 5. Sandbox Executor (`src/fixpilot/sandbox/docker_executor.py`)

Runs tests in a Docker sandbox with security controls:

- `--network none` - Disables network
- `--memory 1g` - Memory limit
- `--cpus 1` - CPU limit
- `--pids-limit 128` - PID limit
- `--user nonroot:nonroot` - Non-root user
- Read-only mount of workspace (`:ro`)

### 6. Agents

#### Investigator (`src/fixpilot/agents/investigator.py`)

Analyzes failure diagnostics and produces root-cause hypotheses:

- Parses pytest output and tracebacks using built-in parsers
- Sends prompts to LLM if provider available
- Falls back to heuristic investigation without LLM
- Returns `InvestigationResult` with structured hypotheses

#### Planner (`src/fixpilot/agents/planner.py`)

Converts investigation results into repair plans:

- Identifies files to change (and protected files to avoid)
- Builds repair steps based on hypotheses
- Identifies regression risks
- Builds validation commands and rollback strategies
- Produces `RepairPlan` Pydantic model

#### Repairer (`src/fixpilot/agents/repairer.py`)

Generates minimal unified diff patches:

- Uses LLM to produce precise patches
- Falls back to minimal patch structure if LLM unavailable
- Outputs only unified diff format (no markdown code blocks)
- Requirements: minimal changes, no refactoring, no unrelated modifications

#### Verifier (`src/fixpilot/agents/verifier.py`)

Compares pre-patch and post-patch test results:

- Checks criterion 1: Test command completed normally (no timeout)
- Checks criterion 2: Previously failing tests now pass
- Checks criterion 3: No new failures relative to baseline
- Detects regressions (new failures or tests that were passing but now fail)
- Returns status: `success` | `retry` | `stop` | `regression`

#### RetryManager (`src/fixpilot/agents/retry_manager.py`)

Manages bounded retry attempts:

- Default max retries: 2 (configurable)
- Retry only if previously failing tests now pass with new evidence
- Stop on regression, `stop` status without new evidence, or max retries reached
- Records each attempt with patch and test results

### 7. Patching (`src/fixpilot/patching/validator.py`)

Validates and applies unified diff patches:

**Safety checks**:

- Rejects absolute paths (paths starting with `/`)
- Rejects directory traversal (`..`)
- Rejects protected file patterns (`.env`, `.git`, `fixpilot.toml`, `Dockerfile`, `.fixpilot`, `artifacts`)
- Limits max files changed (default: 5)
- Limits max changed lines (default: 300)
- Validates target files exist in workspace

**Application**:

- Creates backup before applying
- Parses unified diff hunks
- Applies hunks to existing file content
- Supports new file creation
- Supports safe rollback via backup

### 8. Storage (`src/fixpilot/storage/database.py`)

SQLite backend for run history persistence:

- **Runs table**: `run_id`, `target_display_path`, `started_at`, `finished_at`, `status`, `mode`, `baseline_exit_code`, `final_exit_code`, `retry_count`, `model_name`, `report_path`, `error_summary`
- **Attempts table**: `attempt_id`, `run_id`, `attempt_number`, `root_cause_summary`, `patch_summary`, `patch_path`, `approval_status`, `test_status`, `verification_status`, `created_at`
- **Events table**: Audit log of workflow stages

### 9. Schemas (Pydantic models)

| Schema | Purpose |
|--------|---------|
| `ExecutionResult` | Structured test execution output |
| `InvestigationResult` | Root-cause investigation output |
| `RootCauseHypothesis` | Individual hypothesis with confidence |
| `RepairPlan` | Structured repair plan |
| `PatchResult` | Patch generation output |
| `FixPilotState` | Typed state for workflow tracking |
| `DiagnosticEvidence` | Parsed diagnostic information |

### 10. Reporting (`src/fixpilot/reporting/markdown_report.py`)

Generates Markdown reports from run metadata and attempts:

- Run metadata (target, status, model, timestamps)
- Attempt history with verification/test outcomes
- Applied patch diffs
- Limitations notice
- Auto-generated report footer

---

## Execution Flow

### 1. Project Scanning

```python
scan_project(project_path, config)  # Returns inventory summary
```

- Scans Python files, test files, config files
- Detects test command (pytest from config or config files)
- Returns summary with Python file counts and test file list

### 2. Baseline Testing

```python
executor.run_tests(test_cmd, workspace_path)  # Returns ExecutionResult
```

- Runs pytest in Docker sandbox (or locally if Docker unavailable)
- Captures exit code, stdout, stderr, timing
- If baseline passes: workflow ends with "SUCCESS - all tests pass"

### 3. Investigation

```python
investigator.investigate(diagnostics, project_metadata, config)  # Returns InvestigationResult
```

- Parses test output and tracebacks
- Sends prompt to LLM (Gemini provider) for root cause analysis
- Returns hypotheses with explanations, confidence, and evidence

### 4. Planning

```python
planner.create_plan(investigation, config)  # Returns RepairPlan
```

- Identifies files to change from investigation evidence
- Builds repair steps and validation commands
- Identifies regression risks and rollback strategy
- Produces structured `RepairPlan`

### 5. Patch Generation & Approval

```python
repairer.generate_patch(plan, context)  # Returns PatchResult
```

- LLM generates minimal unified diff patch
- Patch is validated for safety (no absolute paths, no traversal, no protected files)
- Human approval required (unless `--yes` flag or `FIXPILOT_APPROVAL_REQUIRED=false`)

### 6. Patch Application & Verification

```python
applier.apply_patch(patch, workspace_path)  # Returns (success, message, backup_path)
```

- Applies patch to disposable workspace
- Runs post-patch tests
- Verifier compares pre-patch vs post-patch results:
  - Status `success`: original tests now pass, no new failures
  - Status `retry`: previously failing tests now pass, retry with new evidence
  - Status `stop`: repair not verified, original tests still fail
  - Status `regression`: new failures introduced

### 7. Retry Loop

If verification status is `retry` and `should_retry()` returns True:

- Increment attempt counter
- Generate new patch with updated diagnostics
- Re-run verification
- Stop after max_retries (default: 2) attempts

### 8. Report Generation

```python
storage.export_report(run_id)  # Returns Markdown report string
```

- Generates comprehensive Markdown report
- Includes run metadata, attempt history, patch diffs
- Appends limitations notice

---

## Key Directories

```
F:\FixPilot Ai\
├── artifacts/              # Database and reports output
├── dashboard/              # Dashboard UI (if applicable)
├── docs/                   # Documentation files
├── sample_projects/        # Test project examples
├── .kilo/                  # Kilo agent configuration
├── .venv/                  # Python virtual environment
├── requirements/           # Python dependencies
│   └── requirements.txt
├── src/                    # Source code
│   └── fixpilot/           # FixPilot Python package
│       ├── __init__.py     # Package init
│       ├── cli.py          # CLI entry point
│       ├── config.py       # Configuration management
│       ├── workflow/       # Workflow engine
│       │   └── engine.py   # Main orchestrator
│       ├── scanner/        # Project scanning
│       │   └── project_scanner.py
│       ├── sandbox/        # Docker sandbox execution
│       │   └── docker_executor.py
│       ├── diagnostics/    # Diagnostic parsing
│       │   ├── pytest_parser.py
│       │   ├── traceback_parser.py
│       │   └── redaction.py
│       ├── agents/         # AI agents
│       │   ├── investigator.py
│       │   ├── planner.py
│       │   ├── repairer.py
│       │   ├── verifier.py
│       │   └── retry_manager.py
│       ├── patching/       # Patch validation/application
│       │   └── validator.py
│       ├── llm/            # LLM provider
│       │   ├── provider.py
│       │   └── gemini_provider.py
│       ├── schemas/        # Pydantic data models
│       ├── storage/        # SQLite storage
│       └── reporting/      # Markdown reporting
├── tests/                  # Test suite
├── .env                    # Environment variables
├── .env.example            # Example environment file
├── .gitignore
├── pyproject.toml          # Project configuration
├── PROJECT_SPEC.md         # Detailed specification
└── README.md               # High-level documentation
```

---

## Requirements

- Python 3.12
- Docker (for sandboxed execution - mandatory for repair workflow)
- Gemini API key (optional for MVP with mocks)
- Google Generative AI package: `pip install google-generativeai`

---

## CLI Usage Examples

```bash
# Check environment
fixpilot doctor

# Scan a project
fixpilot scan /path/to/project

# Run repair workflow (with interactive approval)
fixpilot run /path/to/project

# Run in analysis-only mode (no patch application)
fixpilot run /path/to/project --analysis-only

# Auto-approve patches (use with caution)
fixpilot run /path/to/project --yes

# View run history
fixpilot history

# Show specific run details
fixpilot show run_abc12345def6

# Export run report
fixpilot export run_abc12345def6
```