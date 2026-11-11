# FixPilot AI: Workflow Documentation

## Overview

FixPilot AI is an **autonomous software debugging and self-healing agent** that automates the full debugging loop: from scanning a project and detecting failing tests, through root-cause investigation, repair planning, patch generation, verification, and reporting.

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
| `fixpilot doctor` | Check environment and configuration (including whether the Docker *daemon* is reachable) |
| `fixpilot scan <path>` | Scan a project |
| `fixpilot clone <url>` | Clone a GitHub repository (`--branch`, `--commit`, `--target`, `--force`) |
| `fixpilot run <path>` | Run the full repair workflow |
| `fixpilot run <path> --analysis-only` | Analysis mode, no patch application |
| `fixpilot run <path> --yes` | Auto-approve patches without interactive prompt |
| `fixpilot audit <path>` | Static bug scan (no failing test required) |
| `fixpilot review <path>` | Code quality and architecture review |
| `fixpilot history` | List run history |
| `fixpilot show <run-id>` | Show run details |
| `fixpilot export <run-id>` | Export run report |

Exit codes for `fixpilot run`: `0` verified, `1` not verified / workflow error, `2` blocked (no sandbox).

### 2. Configuration (`src/fixpilot/config.py`)

Loads from `.env` file at project root. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `GEMINI_API_KEY` | `""` | LLM API key |
| `FIXPILOT_MODEL` | `gemini-1.5-flash` | LLM model to use |
| `FIXPILOT_LOG_LEVEL` | `INFO` | Logging level |
| `FIXPILOT_DB_PATH` | `artifacts/fixpilot.sqlite3` | Database path |
| `FIXPILOT_REPORTS_DIR` | `reports` | Report output directory |
| `FIXPILOT_SANDBOX_IMAGE` | `fixpilot-sandbox:latest` | Fallback sandbox image |
| `FIXPILOT_MAX_RETRIES` | `2` | Max repair attempts |
| `FIXPILOT_TIMEOUT_SECONDS` | `120` | Test timeout |
| `FIXPILOT_APPROVAL_REQUIRED` | `true` | Require human approval for patches |
| `FIXPILOT_ANALYSIS_ONLY` | `false` | Analysis-only mode |
| `FIXPILOT_ALLOW_LOCAL_RUNNER` | `false` | Allow running target code on the host when Docker is unavailable (legacy alias of `FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION`) |
| `FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION` | `false` | Allow running target code on the host when Docker is unavailable |
| `FIXPILOT_ALLOW_NETWORK` | `false` | Let the sandbox container reach the network |
| `FIXPILOT_ALLOW_FILE_CREATION` | `false` | Let a patch create new files |
| `FIXPILOT_ALLOW_FILE_DELETION` | `false` | Let a patch delete files |
| `FIXPILOT_KEEP_WORKSPACE` | `false` | Keep the disposable workspace after a run |

Every boolean switch is **fail-safe**: an unset *or blank* variable keeps the
documented default, so a stray `FIXPILOT_APPROVAL_REQUIRED=` line can never
silently disable the human approval gate.

### 3. Workflow Engine (`src/fixpilot/workflow/engine.py`)

Orchestrates the full lifecycle:

- **Project scanning** - Detects project structure and test files (multi-language)
- **Baseline testing** - Runs initial test suite to identify failures
- **Diagnostics collection** - Captures test output, tracebacks, stderr
- **Investigation** - LLM-powered root cause analysis (the raw runner output is included in the prompt)
- **Planning** - Creates structured repair plans
- **Patch generation** - Generates minimal unified diff patches (validated, retried once)
- **Patch validation** - Safety checks before application
- **Approval gate** - Interactive or auto-approval for patch application
- **Patch application** - Applies patches to the disposable workspace
- **Post-patch testing** - Reruns tests to verify fix
- **Verification** - Compares pre/post patch results
- **Retry management** - Bounded retry with rollback (max 2 attempts)
- **Report generation** - Markdown reports

### 4. Project Scanner (`src/fixpilot/scanner/project_scanner.py`)

Responsibilities:

- Validate target path
- Identify project structure across all supported languages
- Detect Git repository and working-tree state
- Detect test configuration (pytest, jest, go test, cargo test, maven, gradle, ...)
- Identify test files using safe discovery (multi-language naming conventions)
- Read relevant source files within configured limits
- Exclude secrets, binary files, generated files, caches, and oversized files

`scan_project_detailed()` returns a structured inventory (`source_files`, `test_files`, `config_files`, `total_lines`, `test_command`); `scan_project()` renders it as a human-readable summary.

**Exclusion patterns** (directories & files): `.git`, `.venv`, `venv`, `.env`, `node_modules`, `__pycache__`, `build`, `dist`, `*.egg-info`, `.pytest_cache`, `.mypy_cache`

**Excluded extensions**: `.pyc`, `.pyo`, `.pyd`, `.so`, `.dll`, `.exe`, `.dat`, `.bin`, `.gz`, `.zip`, `.tar`, `.rar`, `.pdf`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.wmv`, `.avi`, `.mov`, `.mp4`, `.mp3`, `.wav`, `.ogg`, `.flac`

### 5. Sandbox Executor (`src/fixpilot/sandbox/docker_executor.py`)

Runs tests in a Docker sandbox with security controls:

- `--network none` - Disables network (host networking is never used)
- `--memory 1g` - Memory limit
- `--cpus 1` - CPU limit
- `--pids-limit 128` - PID limit
- `--user nonroot:nonroot` - Non-root user
- `--cap-drop ALL`, `--security-opt no-new-privileges`
- Only the disposable workspace is mounted (`:rw`); the Docker socket is never mounted
- Dependency installation is a separate, explicitly enabled phase that may only use bridge networking

Docker exit code `125` (container could not start, e.g. missing image) is reported as an **infrastructure failure** (`exit_code=-1`), not as a failing test suite.

### 6. Agents

#### Investigator (`src/fixpilot/agents/investigator.py`)

Analyzes failure diagnostics and produces root-cause hypotheses:

- Parses test output using the language-specific parser
- Sends the raw runner output, the failure summary and the traceback to the LLM
- Falls back to heuristic investigation without an LLM
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

- Uses the LLM to produce precise patches
- Extracts the diff from the raw response, dropping code fences and surrounding prose
- **Validates** the diff: it must contain at least one `@@` hunk with a real `-`/`+` change. A degenerate diff (headers only) is retried once with a stricter prompt
- If no usable diff can be produced, an **empty patch** is returned so the run reports "no patch" instead of a fake repair
- The plan's `files_not_to_change` list is passed to the patch validator, so a patch can never "fix" a test by editing it

#### Verifier (`src/fixpilot/agents/verifier.py`)

Compares pre-patch and post-patch test results:

- Checks criterion 1: Test command completed normally (no timeout)
- Checks criterion 2: Previously failing tests now pass
- Checks criterion 3: No new failures relative to baseline
- Detects regressions (new failures or tests that were passing but now fail)
- Returns status: `success` | `retry` | `stop` | `regression`
  - `retry` is returned when a repair made **partial** progress (some previously failing tests now pass, others still fail, no new failures) — there is new evidence to act on

#### RetryManager (`src/fixpilot/agents/retry_manager.py`)

Manages bounded retry attempts:

- Default max retries: 2 (configurable via `FIXPILOT_MAX_RETRIES`)
- Retry only if previously failing tests now pass with new evidence
- Stop on regression, `stop` status without new evidence, or max retries reached
- Records each attempt with patch and test results

#### StaticAnalyzer (`src/fixpilot/agents/static_analyzer.py`)

Scans source files for potential bugs without requiring a failing test. Uses the LLM when available and falls back to heuristic checks (broad exception handling, hardcoded secrets, unresolved TODOs). Results are persisted to the `audits` table.

#### CodeReviewer (`src/fixpilot/agents/code_reviewer.py`)

Performs code quality, style and architecture review. Uses the LLM when available and falls back to heuristic linting (line length, `print()` usage). Results are persisted to the `reviews` table.

### 7. Patching (`src/fixpilot/patching/validator.py`)

Validates and applies unified diff patches:

**Safety checks**:

- Rejects absolute paths (POSIX `/...` and Windows `C:\...` / UNC)
- Rejects directory traversal (`..`)
- Rejects protected path components (`.env`, `.git`, `.fixpilot`, `fixpilot.toml`, `artifacts`, `Dockerfile*`)
- Rejects files listed in the repair plan's `files_not_to_change` (e.g. test files)
- Requires every target to resolve **inside** the disposable workspace
- Limits max files changed (default: 5) — counted by full relative path, not basename
- Limits max changed lines (default: 300) — additions **and** removals are counted

**Application**:

- Creates a backup before applying
- Parses unified diff hunks including the `@@ -a,b +c,d @@` line numbers
- Applies hunks at the declared offset, with a bounded search window and exact context matching
- Preserves the original line endings and the trailing newline
- Fails loudly when a hunk's context cannot be located, instead of corrupting the file
- Supports new file creation (`--- /dev/null`)
- Supports safe rollback via backup

### 8. Storage (`src/fixpilot/storage/database.py`)

SQLite backend for run history persistence:

- **Runs table**: `run_id`, `target_display_path`, `started_at`, `finished_at`, `status`, `mode`, `baseline_exit_code`, `final_exit_code`, `retry_count`, `attempt_count`, `model_name`, `report_path`, `error_summary`, `language`, `test_framework`, `test_command`, `build_command`, `repo_url`, `branch`, `commit`
- **Attempts table**: `attempt_id`, `run_id`, `attempt_number`, `root_cause_summary`, `patch_summary`, `patch_path`, `patch_diff`, `approval_status`, `applied_at`, `test_status`, `verification_status`, `created_at`
- **Events table**: Audit log of the workflow stages (`SCAN_PROJECT` → `FINALIZE_REPORT`)
- **Audits table**: static bug scan results
- **Reviews table**: code quality review results

The detected toolchain (`language`, `test_framework`, `test_command`) is written
back onto the run row after detection, because the row is created before the
toolchain is known. `report_path` is stored when the report is written, and
each attempt's diff is also saved as a real `.patch` artifact under
`reports/patches/`.

### 8b. Project configuration (`fixpilot.toml`)

A project may ship a `fixpilot.toml` file. The nested tables defined in
PROJECT_SPEC §20 are flattened onto the run configuration:

| Table | Settings |
|-------|----------|
| `[project]` | `language`, `test_framework`, `test_command`, `build_command`, `exclude`, `max_file_bytes`, `max_context_bytes` |
| `[agent]` | `max_retries`, `approval_required`, `analysis_only`, `max_files_changed`, `max_changed_lines` |
| `[sandbox]` | `image`, `network`, `timeout_seconds`, `memory_limit`, `cpus`, `pids_limit`, `max_output_bytes` |
| `[storage]` | `database_path` |
| `[reporting]` | `output_dir`, `patch_dir`, `redact_absolute_paths` |

Values given on the command line or in the environment always win over the
file. Unknown tables are ignored.


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
| `AuditFinding` / `AuditResult` | Static analysis findings |
| `ReviewIssue` / `ReviewResult` | Code review findings |

### 10. Reporting (`src/fixpilot/reporting/markdown_report.py`)

Generates Markdown reports from run metadata and attempts:

- Run metadata (target, status, model, timestamps, exit codes)
- Error summary
- Attempt history with verification/test/approval outcomes, root cause and the applied patch diff
- Limitations notice
- Auto-generated report footer

This is the single renderer used by `Storage.export_report()`, so CLI exports, dashboard views and engine output always agree.

---

## Execution Flow

### 1. Project Scanning

```python
scan_project_detailed(project_path, config)  # Returns inventory dict
scan_project(project_path, config)            # Returns human-readable summary
```

- Scans source files across all supported languages
- Detects test command (from config or project config files)
- Returns the source/test file inventory

### 2. Baseline Testing

```python
executor.run_tests(test_cmd, workspace_path, language=language)  # Returns ExecutionResult
```

- Runs the test suite in the Docker sandbox
- Captures exit code, stdout, stderr, timing
- If baseline passes: workflow ends with "SUCCESS - all tests pass"

### 3. Investigation

```python
investigator.investigate(diagnostics, project_metadata, config)  # Returns InvestigationResult
```

- Selects the parser matching the detected language and framework
- Sends the raw runner output plus the parsed evidence to the LLM
- Returns hypotheses with explanations, confidence, and evidence

### 4. Planning

```python
planner.create_plan(investigation, config, workspace_path=workspace_path)  # Returns RepairPlan
```

- Identifies files to change from investigation evidence
- Builds repair steps and validation commands
- Identifies regression risks and rollback strategy
- Produces structured `RepairPlan`

### 5. Patch Generation & Approval

```python
repairer.generate_patch(plan, context)  # Returns PatchResult
```

- LLM generates a minimal unified diff patch
- The diff is validated to contain a real change; a degenerate diff is retried once
- The patch is validated for safety (no absolute paths, no traversal, no protected files, no test files)
- Human approval required (unless `--yes` flag or `FIXPILOT_APPROVAL_REQUIRED=false`)

### 6. Patch Application & Verification

```python
applier.apply_patch(patch, workspace_path)  # Returns (success, message, backup_path)
```

- Applies patch to the disposable workspace
- Runs post-patch tests
- Verifier compares pre-patch vs post-patch results:
  - Status `success`: original tests now pass, no new failures
  - Status `retry`: partial progress — some tests fixed, no new failures; retry with new evidence
  - Status `stop`: repair not verified, original tests still fail
  - Status `regression`: new failures introduced

### 7. Retry Loop

If verification status is `retry` and `should_retry()` returns True:

- Increment attempt counter
- Re-read the current file contents from the workspace (the previous attempt may have changed them)
- Generate a new patch
- Re-run verification
- Stop after max_retries (default: 2) attempts

### 8. Report Generation

```python
storage.export_report(run_id)  # Returns Markdown report string
storage.save_report(run_id)    # Writes reports/fixpilot_report_<run_id>.md
```

- Generates a comprehensive Markdown report
- Includes run metadata, attempt history and patch diffs
- Appends the limitations notice

---

## Key Directories

```
F:\FixPilot Ai\
├── artifacts/              # SQLite database
├── dashboard/              # Streamlit dashboard (app.py)
├── docs/                   # Dockerfiles for the sandbox images, demo script
├── reports/                # Generated Markdown reports (git-ignored)
├── requirements/           # requirements.txt (dependency manifest)
├── sample_projects/        # Seeded test fixtures
├── src/                    # Source code
│   └── fixpilot/           # FixPilot Python package
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py          # CLI entry point
│       ├── config.py       # Configuration management
│       ├── logging_config.py
│       ├── workflow/       # Workflow engine
│       │   └── engine.py
│       ├── scanner/        # Project scanning
│       │   └── project_scanner.py
│       ├── sandbox/        # Docker sandbox execution
│       │   └── docker_executor.py
│       ├── diagnostics/    # Diagnostic parsing
│       │   ├── base.py             # Parser base + registry
│       │   ├── pytest_parser.py
│       │   ├── jest_parser.py      # JavaScript + TypeScript
│       │   ├── go_test_parser.py
│       │   ├── cargo_test_parser.py
│       │   ├── junit_parser.py     # java / java-maven / java-gradle
│       │   ├── traceback_parser.py
│       │   └── redaction.py
│       ├── languages/      # Per-language configuration
│       │   ├── base.py
│       │   ├── python.py
│       │   ├── javascript.py
│       │   ├── go.py
│       │   ├── rust.py
│       │   ├── java.py
│       │   └── registry.py
│       ├── agents/         # AI agents
│       │   ├── investigator.py
│       │   ├── planner.py
│       │   ├── repairer.py
│       │   ├── verifier.py
│       │   ├── retry_manager.py
│       │   ├── code_reviewer.py
│       │   └── static_analyzer.py
│       ├── patching/       # Patch validation/application
│       │   └── validator.py
│       ├── llm/            # LLM provider
│       │   ├── provider.py
│       │   └── gemini_provider.py
│       ├── schemas/        # Pydantic data models
│       │   ├── audit.py
│       │   ├── diagnostics.py
│       │   ├── execution.py
│       │   ├── investigation.py
│       │   ├── patch.py
│       │   ├── repair_plan.py
│       │   ├── review.py
│       │   └── state.py
│       ├── storage/        # SQLite storage
│       │   └── database.py
│       ├── reporting/      # Markdown reporting
│       │   └── markdown_report.py
│       └── repository/     # GitHub cloning
│           └── fetcher.py
├── tests/                  # Test suite (unit + integration)
├── .env                    # Environment variables (git-ignored)
├── .env.example            # Example environment file
├── .gitignore
├── pyproject.toml          # Project configuration
├── PROJECT_SPEC.md         # Detailed specification
├── WORKFLOW_DOCUMENTATION.md
├── TASKS.md
├── DEMO.md
└── README.md
```

---

## Requirements

- Python 3.12+
- Docker (for sandboxed execution - mandatory for the repair workflow)
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

# Static analysis and code review
fixpilot audit /path/to/project
fixpilot review /path/to/project

# View run history
fixpilot history

# Show specific run details
fixpilot show run_abc12345def6

# Export run report
fixpilot export run_abc12345def6
```
