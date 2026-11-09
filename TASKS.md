# TASKS.md

## Milestone 0 — Repository and specification

- [x] Inspect repository ✓
- [x] Confirm Python/package manager/CLI choice
- [x] Create or validate folder structure
- [x] Add README, .gitignore, .env.example, dependency manifest
- [x] Add project version and license placeholder if needed

**Acceptance:**
- Fresh setup instructions are complete
- No secrets are committed
- `fixpilot version` works

---

## Milestone 1 — Scanner and CLI foundation

- [x] Implement CLI skeleton
- [x] Implement safe project path validation
- [x] Implement project scanner and exclusions
- [x] Implement `doctor` and `scan`
- [x] Add unit tests

**Acceptance:**
- Scanner does not execute target code
- It cannot escape target root
- It handles missing/invalid paths clearly
- Tests pass

---

## Milestone 2 — Sandbox and baseline test runner

- [ ] Build/pin approved Docker image
- [x] Implement Docker executor with network disabled and resource/time limits
- [x] Implement safe pytest command
- [x] Capture structured execution output
- [x] Add test fixtures and integration tests

**Acceptance:**
- Target code never runs on host
- Sandbox failure is `BLOCKED`, not host fallback
- Timeout and output limits work
- Baseline test result is reproducible

---

## Milestone 3 — Diagnostic collection

- [x] Parse pytest output and tracebacks
- [x] Extract failing test, exception, frames, source snippets
- [x] Redact sensitive data
- [x] Store diagnostic artifact

**Acceptance:**
- Correctly parse fixture cases
- Malformed output does not crash the app
- Secret-like values are redacted

---

## Milestone 4 — LLM provider and Investigator

- [x] Add provider abstraction
- [x] Integrate Gemini behind configurable model
- [x] Create investigator prompt and structured schema
- [x] Validate responses and handle provider errors
- [x] Mock provider in tests

**Acceptance:**
- Investigation returns structured hypotheses and evidence
- Invalid model output is rejected/retried safely
- No secrets or prompt-injection instructions are followed
- Unit tests work without a live API

---

## Milestone 5 — Planner and Repairer

- [x] Create repair-plan schema
- [x] Create patch-generation prompt
- [x] Generate unified diff
- [x] Validate patch paths, limits, and protected files
- [x] Add patch preview

**Acceptance:**
- No direct model writes to target files
- Unsafe patches are rejected
- Patch only touches permitted workspace files
- Analysis-only mode works

---

## Milestone 6 — Approval, apply, retry, verification

- [x] Implement approval gate
- [x] Apply patches to disposable workspace
- [x] Rerun baseline test command
- [x] Compare results and classify success/regression
- [x] Implement bounded retry and rollback

**Acceptance:**
- Original project remains unchanged
- Successful repair meets objective criteria
- Failed repair does not claim success
- Retry limit is enforced
- Regression is detected and reported

---

## Milestone 7 — Persistence and reports

- [x] Implement SQLite schema/migrations
- [x] Store runs and attempts
- [x] Generate Markdown reports
- [x] Add history/show/export commands

**Acceptance:**
- Completed runs remain available after restart
- Report matches actual stored test results
- Secrets are not persisted

---

## Milestone 8 — Dashboard

- [ ] Implement Streamlit UI using existing service/workflow APIs
- [ ] Add run monitor, diagnostics, patch review, verification, history

**Acceptance:**
- UI does not duplicate core logic
- All statuses are accurate
- Approval is explicit
- UI handles errors and active runs

---

## Milestone 9 — Evaluation and final project package

- [ ] Run seeded benchmark
- [ ] Calculate metrics
- [ ] Fix high-priority bugs
- [ ] Update README and architecture docs
- [ ] Prepare screenshots/demo script
- [ ] Prepare final project report and limitations

**Acceptance:**
- Demo is repeatable from a clean setup
- Evaluation results are reproducible
- Known limitations are documented
- No unsupported claims