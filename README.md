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
- Sandboxed patch application and verification (Docker sandbox with local fallback)
- Bounded retry with rollback
- Local history, SQLite persistence, and Markdown report storage
- Streamlit monitoring dashboard
- GitHub repository cloning integration
- CLI commands for workflow management

## Supported Languages & Frameworks

| Language | Config Identifiers | Test Frameworks |
|----------|--------------------|-----------------|
| **Python** | `pyproject.toml`, `setup.py`, `requirements.txt` | pytest, unittest |
| **JavaScript** | `package.json` | Jest, Vitest, Mocha, Ava |
| **TypeScript** | `package.json`, `tsconfig.json` | Jest, Vitest |
| **Go** | `go.mod` | `go test`, testify, Ginkgo, goconvey |
| **Rust** | `Cargo.toml` | `cargo test` |
| **Java (Maven)** | `pom.xml` | JUnit 4/5, TestNG |
| **Java (Gradle)** | `build.gradle(.kts)`, `settings.gradle` | JUnit 4/5, TestNG, Spock |

## Architecture

The system follows a state-machine workflow through these stages:
`INITIALIZE → SCAN_PROJECT → BASELINE_TEST → COLLECT_DIAGNOSTICS → INVESTIGATE → PLAN_REPAIR → GENERATE_PATCH → VALIDATE_PATCH → AWAIT_APPROVAL → APPLY_PATCH → POST_PATCH_TEST → VERIFY → RETRY_DECISION → FINALIZE_REPORT`

## Requirements

- Python 3.12+
- Docker (mandatory for non-Python languages; recommended for sandboxing)
- Gemini API key (or mockable LLM provider interface)

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt` or `pip install -e .`
3. Copy `.env.example` to `.env` and configure `GEMINI_API_KEY`
4. Ensure Docker is running (optional for Python local runner): `docker ps`
5. Run `fixpilot doctor` to verify environment

## CLI Usage

```bash
# Environment & System Doctor
fixpilot doctor

# Scan a project
fixpilot scan <project-path>

# Clone a GitHub repository
fixpilot clone <github-url> [--branch <branch>] [--commit <commit>]

# Run repair workflow
fixpilot run <project-path-or-github-url>
fixpilot run <project-path> --analysis-only
fixpilot run <project-path> --yes

# Specify language or commands manually if needed
fixpilot run <project-path> --language go --test-framework "go test"

# Run history & details
fixpilot history
fixpilot show <run-id>
fixpilot export <run-id> --format markdown

# Dashboard
streamlit run dashboard/app.py
```

## Security

- Target code isolation via Docker sandbox (network disabled, memory/CPU/PIDs limited, non-root user)
- Prompt-injection defenses and secret redaction
- Secrets (e.g., API keys) are never logged or persisted in reports/db

## Honest Limitations

- **It cannot fix what isn't tested.** No failing test → it reports "nothing to repair."
- **Passing tests don't guarantee correctness** — the fix might be wrong even if tests pass.
- **LLM diagnosis can be wrong or incomplete.**
- **Non-Python languages need Docker** — the sandbox images (`fixpilot-sandbox:go`, `:node`, `:rust`, `:java`) are mandatory for Go/Rust/Java/JS when toolchains are not available on the host.
- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).

> **In short:** FixPilot is a **test-driven self-healing agent** — it fixes failing tests in Python, JavaScript, TypeScript, Go, Rust, and Java projects.