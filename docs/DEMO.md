# FixPilot AI — Interactive Demo & Benchmark Guide

This guide demonstrates FixPilot AI's autonomous debugging and self-healing workflow across the provided sample projects.

---

## 1. Environment Doctor Check

Confirm that FixPilot AI is correctly configured:

```bash
python -m fixpilot doctor
```

Expected output: Displays current Python version, configured model, timeout, approval settings, and database path.

---

## 2. Project Scanning

Scan any Python project to extract structural metadata, line counts, and test files:

```bash
python -m fixpilot scan sample_projects/off_by_one
```

---

## 3. Baseline Pass Verification (`no_failure`)

Run FixPilot on a clean project where all tests pass:

```bash
python -m fixpilot run sample_projects/no_failure -y
```

**Expected Outcome:**
FixPilot detects that baseline tests pass with exit code `0`, reports that no repair is required, and logs the successful run to SQLite without touching any source files.

---

## 4. Root-Cause Analysis Mode (`off_by_one`)

Run an investigation-only pass to discover bugs without modifying code:

```bash
python -m fixpilot run sample_projects/off_by_one --analysis-only -y
```

**Expected Outcome:**
FixPilot collects test failure output, analyzes stack traces, redacts any sensitive tokens, identifies the hypothesis (e.g. `AssertionError` in `test_sum_range_up_to_10`), and halts safely.

---

## 5. Viewing History and Exporting Reports

Inspect recorded runs and export audit markdown reports:

```bash
# List recent runs
python -m fixpilot history

# Inspect a specific run
python -m fixpilot show <run_id>

# Export a full Markdown report
python -m fixpilot export <run_id>
```

---

## 6. Launching the Web Dashboard

To launch the Streamlit graphical monitoring dashboard:

```bash
streamlit run dashboard/app.py
```

Features included:
- **Home:** Overview metrics, recent runs, and status breakdown.
- **Run History:** Interactive run log with attempts count and timestamps.
- **Run Details:** In-depth attempt timeline, patch previews, and verification outcomes.
- **Reports:** Markdown report previews and downloadable `.md` exports.

