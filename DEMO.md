# FixPilot AI — Demo Walkthrough

## Quick Start

```bash
# 1. Install FixPilot
pip install -e .

# 2. Check your environment
fixpilot doctor

# 3. Run the self-healing agent on a buggy sample project
fixpilot run sample_projects/off_by_one --yes

# 4. Inspect the result
fixpilot history
fixpilot show <run-id>
fixpilot export <run-id>
```

> **Docker:** the sandbox is required for every language. If Docker is not
> running, the run is **BLOCKED** rather than silently executing the target
> project on your machine. To run Python projects locally anyway, set
> `FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION=true` in `.env`.

## What Happens

1. **Scan** — FixPilot detects source and test files and the language/framework.
2. **Baseline** — Runs the test suite and captures failures.
3. **Investigate** — Sends the raw test output, traceback and source context to the LLM.
4. **Plan** — Creates a repair plan identifying files to change and files to protect.
5. **Patch** — Generates a minimal unified diff, validates it, and retries once if the model returns an unusable diff.
6. **Verify** — Applies the patch in the sandbox and reruns the tests.
7. **Report** — Produces a Markdown report with full traceability.

## Sample Projects

| Directory                         | Language   | Bug               |
|-----------------------------------|------------|-------------------|
| `sample_projects/off_by_one`      | Python     | Off-by-one error  |
| `sample_projects/type_error`      | Python     | Type error        |
| `sample_projects/no_failure`      | Python     | No failure (control) |
| `sample_projects/nodejs_jest`     | JavaScript | Calculation bug   |
| `sample_projects/go_sample`       | Go         | Logic error       |
| `sample_projects/rust_sample`     | Rust       | Arithmetic bug    |
| `sample_projects/java_maven`      | Java       | Arithmetic error  |

## Static Analysis and Code Review

These commands do **not** require a failing test:

```bash
fixpilot audit sample_projects/off_by_one
fixpilot review sample_projects/off_by_one
```

- `audit` scans for potential bugs (null dereferences, resource leaks, logic errors, hardcoded secrets, broad exception handling).
- `review` reports code quality and architecture issues.

Both persist their results to the SQLite database (`audits` and `reviews` tables).

## Dashboard

```bash
streamlit run dashboard/app.py
```

Opens a Streamlit UI with run history, outcome charts, attempt details, and report export.

---

## Advanced Options

```bash
# Apply the verified patch to the original project (requires approval)
fixpilot run sample_projects/off_by_one --apply-to-original

# Deterministic demo mode (no LLM, scripted provider)
fixpilot run sample_projects/off_by_one --demo
```

## Honest Limitations

- **It cannot fix what isn't tested.** No failing test → it reports "nothing to repair."
- **Passing tests don't guarantee correctness** — the fix might be wrong even if tests pass.
- **LLM diagnosis can be wrong or incomplete.**
- **Non-Python languages need Docker** — the sandbox images (`fixpilot-sandbox:go`, `:node`, `:rust`, `:java`) are mandatory for Go/Rust/Java/JS because the host toolchain isn't available. On a Windows machine without Docker, only Python runs locally.
- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).
- **The LLM sometimes returns an unusable diff.** FixPilot validates the diff and retries once with a stricter prompt; if it still fails, the run honestly reports "no patch".
- **A patch cannot create or delete files by default** (`FIXPILOT_ALLOW_FILE_CREATION` / `FIXPILOT_ALLOW_FILE_DELETION`).
- **Rust tests written inline (`#[cfg(test)]` inside `src/`) are not discovered as separate test files.**
- **The local runner executes untrusted code on the host.** It is opt-in, but it removes the sandbox guarantee entirely.

> **In short:** FixPilot is a **test-driven self-healing agent** — it fixes failing tests in Python, JavaScript, TypeScript, Go, Rust, and Java projects, but it needs (a) a failing test to work from and (b) Docker for anything other than Python on this machine.
