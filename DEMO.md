# FixPilot AI — Demo Walkthrough

## Quick Start

```bash
# 1. Install FixPilot
pip install -e .

# 2. Check your environment
fixpilot doctor

# 3. Run the self-healing agent on a buggy sample project
fixpilot run sample_projects/off_by_one --yes
```

## What Happens

1. **Scan** — FixPilot detects test files and the language/framework.
2. **Baseline** — Runs the test suite and captures failures.
3. **Investigate** — Sends diagnostic evidence (tracebacks, source code) to the LLM.
4. **Plan** — Creates a repair plan identifying files to change and files to protect.
5. **Patch** — Generates a minimal unified diff from the LLM's diagnosis.
6. **Verify** — Applies the patch in a sandbox and reruns the tests.
7. **Report** — Produces a Markdown report with full traceability.

## Sample Projects

| Directory                         | Language   | Bug               |
|-----------------------------------|------------|-------------------|
| `sample_projects/off_by_one`      | Python     | Off-by-one error  |
| `sample_projects/go_sample`       | Go         | Logic error       |
| `sample_projects/nodejs_jest`     | JavaScript | Calculation bug   |
| `sample_projects/java_maven`      | Java       | Arithmetic error  |

## Dashboard

```bash
streamlit run dashboard/app.py
```

Opens a Streamlit UI with run history, outcome charts, attempt details, and report export.

---

## Honest Limitations

- **It cannot fix what isn't tested.** No failing test → it reports "nothing to repair."
- **Passing tests don't guarantee correctness** — the fix might be wrong even if tests pass.
- **LLM diagnosis can be wrong or incomplete.**
- **Non-Python languages need Docker** — the sandbox images (`fixpilot-sandbox:go`, `:node`, `:rust`, `:java`) are mandatory for Go/Rust/Java/JS because the host toolchain isn't available. On a Windows machine without Docker, only Python runs locally.
- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).

> **In short:** FixPilot is a **test-driven self-healing agent** — it fixes failing tests in Python, JavaScript, TypeScript, Go, Rust, and Java projects, but it needs (a) a failing test to work from and (b) Docker for anything other than Python on this machine.

