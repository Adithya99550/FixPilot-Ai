# FixPilot AI

**FixPilot AI: Autonomous Software Debugging and Self-Healing Agent**

A controlled agentic system that scans a Python project, detects failing tests or runtime errors, investigates the root cause using code and diagnostic evidence, proposes a repair, applies an approved patch in an isolated environment, reruns tests, and either verifies the repair or safely stops and reports failure.

## Problem Statement

Software developers spend substantial time reproducing failures, reading stack traces, locating relevant source code, forming repair hypotheses, editing code, and rerunning tests. Conventional AI assistants can explain errors or suggest code, but a developer often has to coordinate the full debugging loop manually. FixPilot aims to automate that loop while preserving user control, traceability, and safety.

## Features

- Repository scanning and test discovery
- Diagnostic collection and traceback parsing
- LLM-powered root cause investigation
- Structured repair planning
- Minimal unified diff patch generation
- Sandboxed patch application and verification
- Bounded retry with rollback
- Local history and Markdown report storage
- CLI commands for workflow management

## Architecture

The system follows a state-machine workflow through these stages:
`INITIALIZE → SCAN_PROJECT → BASELINE_TEST → COLLECT_DIAGNOSTICS → INVESTIGATE → PLAN_REPAIR → GENERATE_PATCH → VALIDATE_PATCH → AWAIT_APPROVAL → APPLY_PATCH → POST_PATCH_TEST → VERIFY → RETRY_DECISION → FINALIZE_REPORT`

## Requirements

- Python 3.12
- Docker (for sandboxed execution)
- Gemini API key (optional for MVP with mocks)

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt` or `pip install .`
3. Copy `.env.example` and configure `GEMINI_API_KEY`
4. Ensure Docker is running: `docker ps`
5. Run `fixpilot doctor` to verify environment

## CLI Usage

```bash
fixpilot doctor
fixpilot scan <project-path>
fixpilot run <project-path>
fixpilot run <project-path> --analysis-only
fixpilot history
fixpilot show <run-id>
fixpilot version
```

## Demo

See `DEMO.md` for the complete deterministic demonstration steps.

## Security

- Target code never runs on the host; Docker sandbox is mandatory
- Network is disabled by default in the sandbox
- No privileged containers or host Docker socket mounts
- Prompt-injection defenses are active
- Secrets are never logged or persisted

## Known Limitations

- LLM diagnosis may be wrong or incomplete
- Passing tests do not guarantee correctness
- Docker isolation is not a perfect security guarantee
- First release supports Python projects only
- Human approval may be required for patch application