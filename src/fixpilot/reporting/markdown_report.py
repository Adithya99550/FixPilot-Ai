"""FixPilot AI Markdown Report Generator.

Generates comprehensive markdown reports for repair runs according to
PROJECT_SPEC §12.

The report never hides a failure: the baseline result, every attempt, the
patch that was applied, the verification evidence and the *final* test
output are all included, so the outcome of a run can be audited from the
report alone.
"""

import re
from typing import Any, Dict, List, Optional


#: Matches the counters in the summary line pytest prints, e.g.
#: "1 failed, 2 passed, 1 skipped in 0.12s".
_COUNT_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|errors?|skipped|xpassed|xfailed)\b"
)


def _or_na(value: Any, fallback: str = "N/A") -> str:
    """Render a value for the report, turning SQL NULL into ``N/A``.

    ``dict.get(key, default)`` only substitutes the default when the key is
    *absent*; a column that exists but holds NULL would be rendered as the
    literal string ``None``.
    """
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return fallback
    return value


def _test_counts(output: Optional[str]) -> Dict[str, int]:
    """Extract the passed/failed/error/skipped counts from a test output.

    The last summary line of a test run wins - earlier lines may contain
    unrelated numbers.

    Args:
        output: The raw stdout/stderr of a test run.

    Returns:
        A dict with the counts that could be found (possibly empty).
    """
    if not output:
        return {}

    counts: Dict[str, int] = {}
    for line in output.splitlines():
        matches = _COUNT_RE.findall(line)
        if not matches:
            continue
        # Only summary lines carry the counters - a line such as
        # "  3 passed" inside a traceback is not the summary.
        if " in " not in line and " passed" not in line and " failed" not in line:
            continue
        line_counts: Dict[str, int] = {}
        for count, kind in matches:
            kind = kind.lower()
            if kind == "error":
                kind = "error"
            elif kind == "errors":
                kind = "error"
            line_counts[kind] = int(count)
        if line_counts:
            counts = line_counts

    return counts


def _counts_text(counts: Dict[str, int]) -> str:
    """Render the test counts for the report."""
    if not counts:
        return "N/A (no test summary in the output)"
    order = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
    parts = []
    for key in order:
        if counts.get(key):
            parts.append(f"{counts[key]} {key}")
    return ", ".join(parts) if parts else "N/A (no test summary in the output)"


def _excerpt(text: Optional[str], limit: int = 4000) -> str:
    """Return a bounded excerpt of a test output."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [output truncated] ..."


def _outcome_explanation(
    status: str,
    run_data: Dict[str, Any],
    attempts: List[Dict[str, Any]],
) -> List[str]:
    """Explain in plain words why the run ended the way it did."""
    lines: List[str] = []
    baseline_code = run_data.get("baseline_exit_code")
    final_code = run_data.get("final_exit_code")
    error_summary = run_data.get("error_summary") or ""

    if status == "SUCCESS":
        lines.append(
            "**The repair was verified.** The failing test(s) failed before the "
            "patch and passed after it, inside the disposable workspace."
        )
        if final_code is not None:
            lines.append(f"- Final test exit code: `{final_code}` (0 = all tests passed)")
    elif status == "NO_TESTS":
        lines.append(
            "**No tests were found**, so there was nothing to repair and "
            "nothing that could be verified. This is *not* a verified success."
        )
    elif status == "PARTIAL":
        lines.append(
            "**The repair only partially worked.** Some previously failing "
            "tests now pass, others still fail."
        )
    elif status == "REGRESSION":
        lines.append(
            "**The repair introduced new failures.** Tests that passed before "
            "the patch fail afterwards."
        )
    elif status == "REPAIR_FAILED":
        lines.append(
            "**No usable repair could be generated.** The language model did "
            "not return a valid patch, so nothing was applied."
        )
    elif status == "PATCH_INVALID":
        lines.append(
            "**The generated patch was rejected by the validator.** It tried "
            "to escape the workspace or was otherwise unsafe, so it was never "
            "applied."
        )
    elif status == "EXECUTION_FAILED":
        lines.append(
            "**The test command could not be executed at all**, so no verdict "
            "about the code is possible."
        )
    elif status == "TIMEOUT":
        lines.append("**The run timed out.**")
    elif status == "CANCELLED":
        lines.append("**The run was cancelled by the user.**")
    elif status == "REJECTED":
        lines.append("**The proposed patch was rejected by the user.**")
    else:
        lines.append(
            "**The repair could not be verified.** The original failing "
            "test(s) still fail."
        )

    if baseline_code is not None:
        lines.append(f"- Baseline (before the repair) exit code: `{baseline_code}`")
    if final_code is not None and status != "SUCCESS":
        lines.append(f"- Final (after the repair) exit code: `{final_code}`")
    if error_summary:
        lines.append(f"- Reason: {error_summary}")
    if not lines:
        lines.append("*No explanation is available for this run.*")
    return lines


def generate_markdown_report(
    run_data: Dict[str, Any],
    attempts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate a clean markdown report from run metadata and attempts."""
    attempts = attempts or []
    run_id = run_data.get("run_id", "unknown")
    status = str(run_data.get("status", "UNKNOWN")).upper()

    baseline_output = run_data.get("baseline_test_output") or ""
    final_output = run_data.get("final_test_output") or ""
    baseline_counts = _test_counts(baseline_output)
    final_counts = _test_counts(final_output)

    lines = [
        "# FixPilot AI Repair Report",
        f"**Run ID:** `{run_id}`  ",
        f"**Status:** **{status}**  ",
        "**Version:** 0.1.0",
        "",
        "## Summary",
        f"- **Target Project:** `{_or_na(run_data.get('target_display_path'))}`",
        f"- **Mode:** {_or_na(run_data.get('mode'), 'standard')}",
        f"- **Model:** {_or_na(run_data.get('model_name'), 'default')}",
        f"- **Language:** {_or_na(run_data.get('language'))}",
        f"- **Test Framework:** {_or_na(run_data.get('test_framework'))}",
        f"- **Test Command:** `{_or_na(run_data.get('test_command'))}`",
        f"- **Started At:** {_or_na(run_data.get('started_at'))}",
        f"- **Finished At:** {_or_na(run_data.get('finished_at'))}",
        f"- **Baseline Exit Code:** {_or_na(run_data.get('baseline_exit_code'))}",
        f"- **Final Exit Code:** {_or_na(run_data.get('final_exit_code'))}",
        f"- **Retry Count:** {_or_na(run_data.get('retry_count'))}",
        f"- **Total Attempts:** {len(attempts)}",
        "",
        "## Outcome",
        "",
        *_outcome_explanation(status, run_data, attempts),
        "",
    ]

    # ---- Baseline ----------------------------------------------------
    lines.extend([
        "## Baseline Test Result (before the repair)",
        f"- **Exit code:** `{_or_na(run_data.get('baseline_exit_code'))}`",
        f"- **Test counts:** {_counts_text(baseline_counts)}",
        f"- **Final test status:** {_or_na(run_data.get('final_test_status'))}",
        "",
    ])
    if baseline_output:
        lines.extend(["```text", _excerpt(baseline_output), "```", ""])
    else:
        lines.extend(["*No baseline output was recorded.*", ""])

    # ---- Final test result -------------------------------------------
    lines.extend([
        "## Final Test Result (after the repair)",
        f"- **Exit code:** `{_or_na(run_data.get('final_test_exit_code'))}`",
        f"- **Test counts:** {_counts_text(final_counts)}",
        f"- **Status:** {_or_na(run_data.get('final_test_status'))}",
        "",
    ])
    if final_output:
        lines.extend(["```text", _excerpt(final_output), "```", ""])
    else:
        lines.extend(["*No final test output was recorded.*", ""])

    if run_data.get("error_summary"):
        lines.extend([
            "## Error Summary",
            f"```text\n{run_data.get('error_summary')}\n```",
            "",
        ])

    # ---- Attempts ----------------------------------------------------
    lines.append("## Attempt Details")
    if not attempts:
        lines.append("*No attempts were recorded for this run.*")
    else:
        for attempt in attempts:
            num = attempt.get("attempt_number", 1)
            v_status = str(attempt.get("verification_status", "N/A")).upper()
            t_status = str(attempt.get("test_status", "N/A")).upper()
            app_status = str(attempt.get("approval_status", "N/A")).upper()
            apply_status = str(attempt.get("apply_status", "N/A")).upper()

            lines.extend([
                f"### Attempt {num}",
                f"- **Verification Outcome:** `{v_status}`",
                f"- **Test Status:** `{t_status}`",
                f"- **Patch Application:** `{apply_status}`",
                f"- **Approval:** `{app_status}`",
                f"- **Root Cause:** {attempt.get('root_cause_summary', 'N/A')}",
                f"- **Patch Summary:** {attempt.get('patch_summary', 'N/A')}",
                f"- **Timestamp:** {attempt.get('created_at', 'N/A')}",
                "",
            ])

            patch_content = attempt.get("patch_diff") or attempt.get("patch_path")
            if patch_content:
                lines.extend([
                    "**Applied Patch Diff:**",
                    "```diff",
                    patch_content.strip(),
                    "```",
                    "",
                ])
            else:
                lines.extend(["*No patch was produced for this attempt.*", ""])

    # ---- Delivery ----------------------------------------------------
    delivery_status = run_data.get("delivery_status")
    if delivery_status:
        lines.extend([
            "## Delivery To The Original Project",
            f"- **Status:** {delivery_status}",
            "",
        ])
        delivery_files = run_data.get("delivery_files")
        if delivery_files:
            for name in delivery_files:
                lines.append(f"- Changed: `{name}`")
            lines.append("")
        delivery_backup = run_data.get("delivery_backup")
        if delivery_backup:
            lines.extend([
                f"- **Backup of the original files:** `{delivery_backup}`",
                "",
            ])

    lines.extend([
        "---",
        "## Honest Limitations",
        "- **It cannot fix what isn't tested.** No failing test -> it reports 'nothing to repair.'",
        "- **Passing tests don't guarantee correctness** - the fix might be wrong even if tests pass.",
        "- **LLM diagnosis can be wrong or incomplete.**",
        "- **Non-Python languages need Docker** - the sandbox images (`fixpilot-sandbox:go`, `:node`, `:rust`, `:java`) are mandatory for Go/Rust/Java/JS because the host toolchain isn't available. On a Windows machine without Docker, only Python runs locally.",
        "- **Human approval may be required** before a patch is applied (unless `--yes` / auto-approve is set).",
        "- **The original project is only changed after a separate, explicit approval** - the repair is always verified in a disposable copy first.",
        "",
        "> **In short:** FixPilot is a **test-driven self-healing agent** - it fixes failing tests in Python, JavaScript, TypeScript, Go, Rust, and Java projects, but it needs (a) a failing test to work from and (b) Docker for anything other than Python on this machine.",
        "",
        "*Report automatically generated by FixPilot AI*",
    ])

    return "\n".join(lines)
