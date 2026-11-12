# FixPilot AI

**FixPilot AI: Autonomous Software Debugging and Self-Healing Agent**

A controlled agentic system that scans multi-language projects (Python, JavaScript, TypeScript, Go, Rust, Java), detects failing tests or runtime errors, investigates the root cause using code and diagnostic evidence, proposes a repair, applies an approved patch in an isolated environment, reruns tests, and either verifies the repair or safely stops and reports failure.

## Problem Statement

Software developers spend substantial time reproducing failures, reading stack traces, locating relevant source code, forming repair hypotheses, editing code, and rerunning tests. Conventional AI assistants can explain errors or suggest code, but a developer often has to coordinate the full debugging loop manually. FixPilot aims to automate that loop while preserving user control, traceability, and safety.

## Features

- Multi-language support (Python, JavaScript, TypeScript, Go, Rust, Java)
- Repository scanning and automatic test framework discovery
- Diagnostic collection and multi-language traceback parsing (pytest, jest, go test, cargo test, junit)
- LLM-powered root cause investigation
- Structured repair planning
- Minimal unified diff patch generation
- Sandboxed patch application and verification (Docker sandbox with an explicit opt-in local fallback)
- Bounded retry with rollback
- Local history, SQLite persistence, and Markdown report storage
- Static bug scanning (`fixpilot audit`) and code quality review (`fixpilot review`)
- Streamlit monitoring dashboard
- GitHub repository cloning integration
- CLI commands for workflow management

## Supported Languages & Frameworks

| Language | Config Identifiers | Test Frameworks |
|----------|--------------------|-----------------|
| **Python** | `pyproject.toml`, `setup.py`, `requirements.txt` | pytest, unittest |
| **JavaScript** | `package.json` | Jest, Vitest, Mocha, Ava |
| **TypeScript** | `package.json`, `tsconfig.json` | Jest, Vitest |
| **Go** | `go.mod` | `go test`, testify, Ginkgo, Goconvey |
| **Rust** | `Cargo.toml` | `cargo test` |
| **Java (Maven)** | `pom.xml` | JUnit 4/5, TestNG |
| **Java (Gradle)** | `build.gradle(.kts)`, `settings.gradle` | JUnit 4/5, TestNG, Spock |

## Architecture

The system follows a state-machine workflow through these stages:
`INITIALIZE → SCAN_PROJECT → BASELINE_TEST → COLLECT_DIAGNOSTICS → INVESTIGATE → PLAN_REPAIR → GENERATE_PATCH → VALIDATE_PATCH → AWAIT_APPROVAL → APPLY_PATCH → POST_PATCH_TEST → VERIFY → RETRY_DECISION → FINALIZE_REPORT`

See [WORKFLOW_DOCUMENTATION.md](WORKFLOW_DOCUMENTATION.md) for the full component-by-component walkthrough.

## Requirements

- Python 3.12+
- Docker (mandatory for non-Python languages; recommended for sandboxing)
- Gemini API key (or mockable LLM provider interface)

## Setup

1. Clone the repository
2. Install dependencies: `pip install -e .` (or `pip install -r requirements/requirements.txt`)
3. Copy `.env.example` to `.env` and configure `GEMINI_API_KEY`
4. Ensure Docker is running (required for non-Python languages): `docker ps`
5. Run `fixpilot doctor` to verify the environment

> **Windows note:** the CLI forces UTF-8 console output, so `→` and em dashes in
> its messages will not crash a `cp1252` console.

## CLI Usage

The full command set is:

| Command | Purpose |
|---------|---------|
| `fixpilot version` | Print the FixPilot version |
| `fixpilot doctor` | Check environment, config and sandbox policy |
| `fixpilot scan <path>` | Detect the language, test framework and test files |
| `fixpilot clone <url>` | Clone a GitHub repository |
| `fixpilot run <path-or-url>` | Run the full repair workflow |
| `fixpilot audit <path>` | Static bug scan (no failing test required) |
| `fixpilot review <path>` | Code quality and architecture review |
| `fixpilot history` | List recorded runs |
| `fixpilot show <run-id>` | Show the details of one run |
| `fixpilot export <run-id>` | Export a run report as Markdown |

> **Note:** there is **no `fixpilot report` command** — it does not exist and
> will fail with `invalid choice: 'report'`. The report command is
> **`fixpilot export <run-id>`**, which writes the Markdown report to
> `reports/fixpilot_report_<run-id>.md` and prints it to the terminal.

```bash
# Environment & System Doctor
fixpilot doctor

# Version
fixpilot version

# Scan a project
fixpilot scan <project-path>

# Clone a GitHub repository
fixpilot clone <github-url> [--branch <branch>] [--commit <commit>] [--target <dir>] [--force]

# Run repair workflow
fixpilot run <project-path-or-github-url>
fixpilot run <project-path> --analysis-only
fixpilot run <project-path> --yes

# Specify language or commands manually if needed
fixpilot run <project-path> --language go --test-framework "go test"
fixpilot run <project-path> --test-command "pytest -q"
fixpilot run <project-path> --build-command "npm run build"

# Clone options that `run` also accepts
fixpilot run <path> --repo-url <github-url> [--branch <branch>] [--commit <commit>]

# Static bug scan (does not require a failing test)
fixpilot audit <project-path>

# Code quality and architecture review
fixpilot review <project-path>

# Run history & details
fixpilot history
fixpilot show <run-id>

# Export the Markdown report for a run
fixpilot export <run-id>
fixpilot export <run-id> --format markdown

# Dashboard
streamlit run dashboard/app.py
```

### Exit codes

| Command | `0` | `1` | `2` |
|---------|-----|-----|-----|
| `fixpilot run` | Repair verified, or no tests to repair | Repair not verified / workflow failed | Run blocked because the Docker sandbox was unavailable |
| `fixpilot export` | Report exported | Run ID not found or report could not be generated | Unsupported export format |

## Advanced Options

```bash
# Apply the verified patch to the original project (requires approval)
fixpilot run <project-path> --apply-to-original

# Override the test/build commands instead of relying on auto-detection
fixpilot run <project-path> --test-command "pytest -q" --build-command "make build"

# Unsafe: run the target project on the host when Docker is unavailable
fixpilot run <project-path> --allow-unsafe-local-execution
```

> **Note:** there is no `fixpilot run --demo` flag. The workflow always uses the
> configured Gemini provider (`GEMINI_API_KEY` + `FIXPILOT_MODEL`).

## Security

- Target code isolation via Docker sandbox (network disabled, memory/CPU/PIDs limited, non-root user, capabilities dropped)
- Path containment on every patch: absolute paths, `..` traversal and protected paths are rejected, and the target must resolve inside the disposable workspace
- Test files listed in the repair plan are protected — a patch cannot "fix" a test by editing it
- Prompt-injection defenses and secret redaction
- Secrets (e.g., API keys) are never logged or persisted in reports/db
- The GitHub token is sent via an `Authorization` header and is never written into a clone's `.git/config`

### Sandbox policy

Per PROJECT_SPEC §9.3, a sandbox failure is **BLOCKED**, not a host fallback.
If Docker is unavailable the run is refused unless you explicitly opt in:

```bash
FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION=true
```

With that flag set, target project code executes directly on the host.

### Safety switches

Everything below is **off by default**:

| Variable | Effect |
|----------|--------|
| `FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION` | Run target code on the host when Docker is unavailable |
| `FIXPILOT_ALLOW_NETWORK` | Let the sandbox container reach the network |
| `FIXPILOT_ALLOW_DEPENDENCY_INSTALL` | Install project dependencies inside the sandbox |
| `FIXPILOT_ALLOW_FILE_CREATION` | Let a patch create new files |
| `FIXPILOT_ALLOW_FILE_DELETION` | Let a patch delete files |
| `FIXPILOT_KEEP_WORKSPACE` | Keep the disposable workspace after a run |

Every switch is **fail-safe**: an unset *or blank* variable keeps the default,
so a stray `FIXPILOT_APPROVAL_REQUIRED=` line can never silently disable the
human approval gate.

### Project configuration

A project can ship a `fixpilot.toml` file to set the language, test command,
retry budget and sandbox limits:

```toml
[project]
language = "python"
test_command = ["python", "-m", "pytest", "-q"]

[agent]
max_retries = 2
approval_required = true
```

Command line flags and environment variables always take precedence over the
file.

## Honest Limitations

- **It cannot fix what isn't tested.** No failing test → it reports "nothing to repair."
- **Passing tests don't guarantee correctness** — the fix might be wrong even if tests pass.
- **LLM diagnosis can be wrong or incomplete.**
- **Non-Python languages need Docker** — the sandbox images (`fixpilot-sandbox:go`, `:node`, `:rust`, `:java`) are mandatory for Go/Rust/Java/JS when toolchains are not available on the host.
- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).
- **The LLM sometimes returns an unusable diff.** FixPilot validates the diff and retries once with a stricter prompt; if it still fails the run reports "no patch" rather than claiming a repair it cannot apply.
- **A patch cannot create or delete files by default.** Enable `FIXPILOT_ALLOW_FILE_CREATION` / `FIXPILOT_ALLOW_FILE_DELETION` if a repair legitimately needs to.
- **JavaScript/TypeScript projects need `--verbose`-style output.** The Jest parser handles both the default and the verbose reporter, but the default reporter gives less detail per failure.
- **Rust tests written inline (`#[cfg(test)]` inside `src/`) are not discovered as separate test files.**
- **The local runner executes untrusted code on the host.** It is opt-in, but it removes the sandbox guarantee entirely.

> **In short:** FixPilot is a **test-driven self-healing agent** — it fixes failing tests in Python, JavaScript, TypeScript, Go, Rust, and Java projects.
