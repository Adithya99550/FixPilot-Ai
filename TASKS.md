# TASKS.md

## Milestone 0 — Repository and specification

- [x] Inspect repository ✓
- [ ] Confirm Python/package manager/CLI choice
- [ ] Create or validate folder structure
- [ ] Add README, .gitignore, .env.example, dependency manifest
- [ ] Add project version and license placeholder if needed

**Acceptance:**
- Fresh setup instructions are complete
- No secrets are committed
- `fixpilot version` works

---

## Milestone 1 — Scanner and CLI foundation

- [ ] Implement CLI skeleton
- [ ] Implement safe project path validation
- [ ] Implement project scanner and exclusions
- [ ] Implement `doctor` and `scan`
- [ ] Add unit tests

**Acceptance:**
- Scanner does not execute target code
- It cannot escape target root
- It handles missing/invalid paths clearly
- Tests pass

---

## Milestone 2 — Sandbox and baseline test runner

- [ ] Build/pin approved Docker image
- [ ] Implement Docker executor with network disabled and resource/time limits
- [ ] Implement safe pytest command
- [ ] Capture structured execution output
- [ ] Add test fixtures and integration tests

**Acceptance:**
- Target code never runs on host
- Sandbox failure is `BLOCKED`, not host fallback
- Timeout and output limits work
- Baseline test result is reproducible

---

## Milestone 3 — Diagnostic collection

- [ ] Parse pytest output and tracebacks
- [ ] Extract failing test, exception, frames, source snippets
- [ ] Redact sensitive data
- [ ] Store diagnostic artifact

**Acceptance:**
- Correctly parse fixture cases
- Malformed output does not crash the app
- Secret-like values are redacted

---

## Milestone 4 — LLM provider and Investigator

- [ ] Add provider abstraction
- [ ] Integrate Gemini behind configurable model
- [ ] Create investigator prompt and structured schema
- [ ] Validate responses and handle provider errors
- [ ] Mock provider in tests

**Acceptance:**
- Investigation returns structured hypotheses and evidence
- Invalid model output is rejected/retried safely
- No secrets or prompt-injection instructions are followed
- Unit tests work without a live API

---

## Milestone 5 — Planner and Repairer

- [ ] Create repair-plan schema
- [ ] Create patch-generation prompt
- [ ] Generate unified diff
- [ ] Validate patch paths, limits, and protected files
- [ ] Add patch preview

**Acceptance:**
- No direct model writes to target files
- Unsafe patches are rejected
- Patch only touches permitted workspace files
- Analysis-only mode works

---

## Milestone 6 — Approval, apply, retry, verification

- [ ] Implement approval gate
- [ ] Apply patches to disposable workspace
- [ ] Rerun baseline test command
- [ ] Compare results and classify success/regression
- [ ] Implement bounded retry and rollback

**Acceptance:**
- Original project remains unchanged
- Successful repair meets objective criteria
- Failed repair does not claim success
- Retry limit is enforced
- Regression is detected and reported

---

## Milestone 7 — Persistence and reports

- [ ] Implement SQLite schema/migrations
- [ ] Store runs and attempts
- [ ] Generate Markdown reports
- [ ] Add history/show/export commands

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