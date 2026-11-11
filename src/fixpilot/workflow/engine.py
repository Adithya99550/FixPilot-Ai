"""FixPilot AI Workflow Engine.

Orchestrates the autonomous debugging and self-healing lifecycle:
Scan -> Baseline -> Diagnostics -> Investigation -> Planning -> Patching ->
Approval -> Verification -> Storage/Report.

Key guarantees
--------------
- The target project's code is executed **inside the Docker sandbox** by
  default. Running it on the host requires an explicit opt-in
  (``FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION``) and is never a silent
  fallback.
- Every repair attempt works on the *current* state of the disposable
  workspace: file contents, test output and diagnostics are refreshed before
  each attempt.
- Identical patches are never applied twice and the run stops as soon as the
  verification confirms success.
- The reported status always reflects the real outcome of the run.
"""

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.config import get_config
from fixpilot.scanner.project_scanner import scan_project, scan_project_detailed
from fixpilot.sandbox import create_executor
from fixpilot.sandbox.local_executor import LocalExecutor  # noqa: F401  (re-export)
from fixpilot.diagnostics import parse_pytest_output, PARSER_REGISTRY
from fixpilot.llm.provider import BaseLLMProvider, GeminiProvider
from fixpilot.agents.investigator import Investigator
from fixpilot.agents.planner import Planner
from fixpilot.agents.repairer import Repairer, RepairGenerationError
from fixpilot.agents.verifier import Verifier
from fixpilot.agents.retry_manager import RetryManager
from fixpilot.patching.validator import PatchApplier
from fixpilot.storage.database import Storage
from fixpilot.schemas.execution import ExecutionResult, RunStatus
from fixpilot.languages import detect_language, detect_test_framework, get_language_config

logger = logging.getLogger("fixpilot.workflow")

#: Maximum number of *identical* invalid patches tolerated before the run
#: gives up (the model is clearly not able to produce a usable patch).
MAX_CONSECUTIVE_INVALID_PATCHES = 2


class WorkflowEngine:
    """FixPilot end-to-end self-healing workflow orchestrator."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        storage: Optional[Storage] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        executor: Optional[Any] = None,
    ):
        self.config = config or get_config()
        self.storage = storage or Storage(
            self.config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"),
            reports_dir=self.config.get("FIXPILOT_REPORTS_DIR", "reports"),
        )

        # LLM Provider setup
        if llm_provider:
            self.llm_provider = llm_provider
        else:
            api_key = self.config.get("GEMINI_API_KEY")
            if api_key:
                try:
                    self.llm_provider = GeminiProvider(
                        api_key=api_key,
                        model=self.config.get("FIXPILOT_MODEL", "gemini-1.5-flash"),
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Could not initialise the Gemini provider: %s", exc)
                    self.llm_provider = None
            else:
                self.llm_provider = None

        # Sandbox / Runner setup. The very same policy is used by the CLI and
        # the dashboard: Docker first, host execution only on explicit opt-in.
        self.executor = create_executor(self.config, executor=executor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        project_path: Path,
        analysis_only: bool = False,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """Execute the full repair workflow on a target project.

        Args:
            project_path: The project to analyse/repair.
            analysis_only: Stop after the investigation stage.
            auto_approve: Skip the interactive patch approval gate.

        Returns:
            A dict with at least ``run_id`` and ``status``.
        """
        project_path = Path(project_path).resolve()
        if not project_path.is_dir():
            raise ValueError(f"Project directory does not exist: {project_path}")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_config = dict(self.config)
        run_config["target_path"] = str(project_path)
        run_config["mode"] = "analysis" if analysis_only else "repair"
        self.storage.start_run(run_id, run_config)

        # Create isolated disposable copy so original project is untouched
        temp_dir = tempfile.mkdtemp(prefix="fixpilot_work_")
        workspace_path = Path(temp_dir)
        keep_workspace = bool(self.config.get("FIXPILOT_KEEP_WORKSPACE", False))
        try:
            shutil.copytree(project_path, workspace_path, dirs_exist_ok=True)
            return self._run_pipeline(
                run_id=run_id,
                project_path=project_path,
                workspace_path=workspace_path,
                analysis_only=analysis_only,
                auto_approve=auto_approve,
            )
        except KeyboardInterrupt:
            print("\n[!] Run cancelled by the user.")
            self.storage.complete_run(
                run_id, RunStatus.CANCELLED, exit_code=1,
                error_summary="Cancelled by the user",
            )
            self.storage.save_report(run_id)
            return {"run_id": run_id, "status": RunStatus.CANCELLED,
                    "reason": "Cancelled by the user"}
        except Exception as exc:
            # Never leave a run permanently PENDING: record the failure so
            # the history and the report stay consistent.
            print(f"\n[!] Workflow failed: {exc}")
            try:
                self.storage.complete_run(
                    run_id, RunStatus.FAILED, exit_code=1,
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
                self.storage.log_event(
                    run_id, "FINALIZE_REPORT",
                    f"Workflow error: {type(exc).__name__}: {exc}",
                    level="ERROR",
                )
                self.storage.save_report(run_id)
            except Exception:
                pass
            raise
        finally:
            if keep_workspace:
                print(f"[i] Disposable workspace kept at: {workspace_path}")
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        run_id: str,
        project_path: Path,
        workspace_path: Path,
        analysis_only: bool,
        auto_approve: bool,
    ) -> Dict[str, Any]:
        print(f"\n[1/6] Scanning project: {project_path}")

        language, test_framework, test_cmd, build_cmd = self._resolve_toolchain(
            workspace_path
        )

        # The run row is written before the toolchain is detected, so the
        # detected values are written back here.
        self.storage.set_run_toolchain(
            run_id,
            language,
            test_framework,
            " ".join(test_cmd),
            " ".join(build_cmd) if build_cmd else "",
        )
        self.storage.log_event(
            run_id, "SCAN_PROJECT",
            f"Detected language={language} framework={test_framework}",
            metadata={"language": language, "test_framework": test_framework},
        )

        scan_data = scan_project_detailed(workspace_path, self.config)
        scan_info = scan_project(workspace_path, self.config)
        scan_files = [
            entry["path"]
            for entry in (scan_data.get("source_files") or [])
            + (scan_data.get("test_files") or [])
        ]

        # Run build command if available (via executor)
        if build_cmd:
            print(f"\n[2/6] Running build command: {' '.join(build_cmd)}")
            build_result = self.executor.run_tests(
                build_cmd, workspace_path, language=language, build_command=None
            )
            if build_result.timed_out:
                print("ERROR: Build timed out.")
                return self._finish(
                    run_id, RunStatus.TIMEOUT, build_result.exit_code,
                    "Build timed out",
                )
            if build_result.exit_code != 0:
                print(f"Build failed with exit code: {build_result.exit_code}")
                print(f"Build stderr: {build_result.stderr[:500]}")

        print("\n[3/6] Running baseline tests...")
        baseline_result = self.executor.run_tests(test_cmd, workspace_path, language=language)
        self.storage.log_event(
            run_id, "BASELINE_TEST",
            f"Baseline exit code: {baseline_result.exit_code}",
            metadata={"exit_code": baseline_result.exit_code},
        )

        if baseline_result.timed_out:
            print("ERROR: Baseline tests timed out.")
            return self._finish(
                run_id, RunStatus.TIMEOUT, baseline_result.exit_code,
                "Baseline tests timed out",
                baseline_exit_code=baseline_result.exit_code,
            )

        if baseline_result.exit_code == -1 and not baseline_result.stdout:
            print("ERROR: The test command could not be executed.")
            return self._finish(
                run_id, RunStatus.EXECUTION_FAILED, baseline_result.exit_code,
                baseline_result.stderr or "Test command could not be executed",
                baseline_exit_code=baseline_result.exit_code,
            )

        if baseline_result.exit_code == 0:
            print("Baseline tests passed - no failing tests detected. Nothing to repair.")
            return self._finish(
                run_id, RunStatus.SUCCESS, 0, "No failing tests",
                message="All tests pass",
                final_result=baseline_result,
                baseline_exit_code=baseline_result.exit_code,
            )

        # pytest exits with 5 when it collected no tests at all. There is
        # nothing to repair and nothing to verify, so do not ask the LLM to
        # "fix" a project that has no tests. The run is *not* a success:
        # no test ever ran.
        if baseline_result.exit_code == 5 and (
            "no tests ran" in (baseline_result.stdout + baseline_result.stderr).lower()
            or "no tests collected" in (baseline_result.stdout + baseline_result.stderr).lower()
        ):
            print("No tests were collected - the repair cannot be verified.")
            return self._finish(
                run_id, RunStatus.NO_TESTS, baseline_result.exit_code,
                "No tests collected - nothing to verify",
                message="No tests found; nothing to repair",
                final_result=baseline_result,
                baseline_exit_code=baseline_result.exit_code,
            )

        print(f"Detected test failures (exit code: {baseline_result.exit_code})")

        # Diagnostics & Investigation
        print("\n[4/6] Extracting diagnostics & investigating root cause...")

        diagnostics = self._build_diagnostics(baseline_result, language, test_framework)
        self.storage.log_event(
            run_id, "COLLECT_DIAGNOSTICS",
            f"Collected diagnostics for {language}/{test_framework}",
        )

        investigator = Investigator(self.llm_provider)
        investigation = investigator.investigate(
            diagnostics=diagnostics,
            project_metadata={
                "path": str(workspace_path),
                "scan": scan_info,
                "language": language,
                "test_framework": test_framework,
                # The raw runner output is the most valuable evidence the
                # model gets - without it it only sees a one-line summary.
                "test_output": diagnostics.get("test_output", ""),
                "stderr": diagnostics.get("stderr", ""),
                "affected_files": scan_files,
                "test_summary": (
                    f"{test_framework} suite in {workspace_path.name}"
                    if test_framework
                    else "unknown test suite"
                ),
            },
            config=self.config,
        )
        self.storage.log_event(
            run_id, "INVESTIGATE",
            f"{len(investigation.root_cause_hypotheses)} hypothesis(es)",
        )

        print(
            f"Investigation completed: "
            f"{len(investigation.root_cause_hypotheses)} hypothesis(es) found."
        )
        for i, hyp in enumerate(investigation.root_cause_hypotheses, 1):
            print(f"  {i}. {hyp.explanation} (Confidence: {hyp.confidence})")

        if analysis_only:
            print("\nAnalysis-only mode requested. Halting repair workflow.")
            return self._finish(
                run_id, RunStatus.SUCCESS, baseline_result.exit_code,
                "Analysis completed",
                investigation=investigation,
                final_result=baseline_result,
                baseline_exit_code=baseline_result.exit_code,
            )

        # Planning
        print("\n[5/6] Creating repair plan...")
        planner = Planner()
        plan = planner.create_plan(investigation, self.config, workspace_path=workspace_path)
        # Add language context to plan
        plan.language = language
        plan.test_framework = test_framework

        # A plan without a target file is useless: the repairer would have no
        # source code to work with. Fall back to the files the failing tests
        # point at.
        if not plan.files_to_change:
            fallback_files = self._files_from_diagnostics(
                diagnostics, workspace_path.resolve()
            )
            if fallback_files:
                print(
                    "[!] The plan named no file - falling back to the files "
                    f"referenced by the failing tests: {', '.join(fallback_files)}"
                )
                plan.files_to_change = fallback_files
        print(f"Plan goal: {plan.goal}")
        print(
            f"Files to modify: "
            f"{', '.join(plan.files_to_change) if plan.files_to_change else 'None specified'}"
        )
        self.storage.log_event(
            run_id, "PLAN_REPAIR",
            f"Plan: {plan.goal}",
            metadata={
                "files_to_change": list(plan.files_to_change),
                "files_not_to_change": list(plan.files_not_to_change),
            },
        )

        # Repair & Verification Loop
        print("\n[6/6] Executing repair and verification loop...")
        repairer = Repairer(llm_provider=self.llm_provider)
        verifier = Verifier()
        retry_manager = RetryManager(self.config, workspace_path=workspace_path)

        # The repair plan lists files that must not be touched (test files,
        # protected paths). Enforce it in the patch validator so a repair can
        # never "fix" a test by editing it.
        applier_config = dict(self.config)
        protected = list(getattr(plan, "files_not_to_change", []) or [])
        if protected:
            applier_config["protected_paths"] = protected
        applier = PatchApplier(applier_config)

        attempt_num = 0
        current_pre_result = baseline_result
        current_diagnostics = diagnostics
        final_status = RunStatus.FAILED
        final_reason = "Repair was not verified"
        final_result: Optional[ExecutionResult] = baseline_result
        seen_patch_hashes: Dict[str, int] = {}
        consecutive_invalid = 0
        verification: Dict[str, Any] = {}

        while attempt_num < retry_manager.max_retries:
            attempt_num += 1
            attempt_id = f"att_{run_id}_{attempt_num}"
            print(f"\n--- Attempt {attempt_num}/{retry_manager.max_retries} ---")

            # Always work from the current workspace state: a previous
            # attempt may already have modified these files.
            file_contents = self._collect_file_contents(
                workspace_path, plan, current_diagnostics
            )

            # Refresh the diagnostics with the latest test output so the
            # repairer always works on the freshest evidence.
            current_diagnostics = self._build_diagnostics(
                current_pre_result, language, test_framework
            )
            if not file_contents:
                # The diagnostics were refreshed after the file collection -
                # try again with the fresh evidence before giving up.
                file_contents = self._collect_file_contents(
                    workspace_path, plan, current_diagnostics
                )

            # On a retry, re-investigate with the new evidence and refresh
            # the plan so the next attempt is based on the current state.
            if attempt_num > 1:
                investigation = investigator.investigate(
                    diagnostics=current_diagnostics,
                    project_metadata={
                        "path": str(workspace_path),
                        "scan": scan_info,
                        "language": language,
                    },
                    config=self.config,
                )
                refreshed_plan = planner.create_plan(
                    investigation, self.config, workspace_path=workspace_path
                )
                refreshed_plan.language = language
                refreshed_plan.test_framework = test_framework
                if refreshed_plan.files_to_change:
                    plan = refreshed_plan
                    applier_config["protected_paths"] = list(
                        getattr(plan, "files_not_to_change", []) or []
                    )
                    applier = PatchApplier(applier_config)
                    print(f"Updated plan goal: {plan.goal}")

            # ---- Generate the patch ----------------------------------
            try:
                patch_result = repairer.generate_patch(
                    plan,
                    {
                        "file_contents": file_contents,
                        "changed_files": plan.files_to_change,
                        "test_output": current_pre_result.stdout,
                        "diagnostics": current_diagnostics,
                    },
                )
            except RepairGenerationError as exc:
                print(f"Repair generation failed: {exc}")
                self.storage.create_attempt(
                    attempt_id, run_id, attempt_num,
                    self._failed_patch_result(exc), self.config,
                )
                self.storage.update_attempt(
                    attempt_id, "ERROR", "REPAIR_FAILED", approval_status="NOT_REQUESTED"
                )
                final_status = RunStatus.REPAIR_FAILED
                final_reason = str(exc)
                break

            self.storage.create_attempt(
                attempt_id, run_id, attempt_num, patch_result, self.config
            )
            self.storage.log_event(
                run_id, "GENERATE_PATCH",
                f"Attempt {attempt_num}: generated a patch",
                metadata={"attempt": attempt_num, "patch_hash": patch_result.patch_hash},
            )

            if not patch_result.patch or not patch_result.patch.strip():
                print("No patch diff generated.")
                self.storage.update_attempt(attempt_id, "NO_PATCH", "STOP")
                final_status = RunStatus.REPAIR_FAILED
                final_reason = "The repairer did not produce a patch"
                break

            # ---- Validate the patch ----------------------------------
            is_valid, validation_msg = applier.validate_patch(
                patch_result.patch, workspace_path
            )
            self.storage.log_event(
                run_id, "VALIDATE_PATCH",
                "Patch accepted" if is_valid else f"Patch rejected: {validation_msg}",
                level="INFO" if is_valid else "WARNING",
                metadata={"attempt": attempt_num},
            )
            if not is_valid:
                print(f"Patch validation failed: {validation_msg}")
                self.storage.update_attempt(
                    attempt_id, "INVALID_PATCH", "REJECTED",
                    approval_status="NOT_REQUESTED",
                )
                consecutive_invalid += 1
                if consecutive_invalid >= MAX_CONSECUTIVE_INVALID_PATCHES:
                    final_status = RunStatus.PATCH_INVALID
                    final_reason = (
                        f"The model repeatedly produced invalid patches: "
                        f"{validation_msg}"
                    )
                    break
                continue

            consecutive_invalid = 0

            # ---- Never apply the same patch twice ---------------------
            patch_hash = PatchApplier.patch_hash(patch_result.patch)
            if patch_hash in seen_patch_hashes:
                print(
                    "The model produced a patch that was already tried and "
                    "failed - stopping to avoid an endless loop."
                )
                self.storage.update_attempt(
                    attempt_id, "REPEATED_PATCH", "REJECTED",
                    approval_status="NOT_REQUESTED",
                )
                final_status = RunStatus.FAILED
                final_reason = (
                    "The model repeated an identical patch that had already "
                    "failed"
                )
                break
            seen_patch_hashes[patch_hash] = attempt_num

            # ---- Approval gate ---------------------------------------
            approval_required = self.config.get("FIXPILOT_APPROVAL_REQUIRED", True)
            if approval_required and not auto_approve:
                print(f"\nPatch Preview:\n{patch_result.patch}\n")
                approved = self._ask_for_approval()
                if not approved:
                    print("Patch rejected by user.")
                    self.storage.update_attempt(
                        attempt_id, "ABORTED", "USER_REJECTED", approval_status="REJECTED"
                    )
                    final_status = RunStatus.REJECTED
                    final_reason = "The patch was rejected by the user"
                    break
                self.storage.update_attempt(attempt_id, approval_status="APPROVED")
                self.storage.log_event(
                    run_id, "AWAIT_APPROVAL", "Patch approved by the user"
                )
            else:
                self.storage.update_attempt(attempt_id, approval_status="AUTO_APPROVED")
                self.storage.log_event(
                    run_id, "AWAIT_APPROVAL", "Patch auto-approved", level="INFO"
                )

            # ---- Apply the patch -------------------------------------
            applied, apply_msg, _backup_path = applier.apply_patch(
                patch_result.patch, workspace_path, create_backup=True
            )
            self.storage.log_event(
                run_id, "APPLY_PATCH",
                "Patch applied" if applied else f"Patch failed to apply: {apply_msg}",
                level="INFO" if applied else "WARNING",
                metadata={"attempt": attempt_num},
            )
            if not applied:
                print(f"Failed to apply patch: {apply_msg}")
                self.storage.update_attempt(attempt_id, "APPLY_FAILED", "RETRY")
                final_reason = apply_msg
                continue

            # ---- Run the tests again ----------------------------------
            post_result = self.executor.run_tests(
                test_cmd, workspace_path, language=language
            )
            self.storage.log_event(
                run_id, "POST_PATCH_TEST",
                f"Post-patch exit code: {post_result.exit_code}",
                metadata={"exit_code": post_result.exit_code},
            )
            final_result = post_result
            verification = verifier.verify(
                current_pre_result, post_result, baseline_result, self.config
            )
            v_status = verification.get("status", "stop")
            print(f"Verification result: {v_status.upper()} - {verification.get('evidence', '')}")
            self.storage.log_event(
                run_id, "VERIFY",
                f"{v_status.upper()}: {verification.get('evidence', '')}",
                level="INFO" if v_status == "success" else "WARNING",
                metadata={"attempt": attempt_num, "status": v_status},
            )

            test_status_str = "PASS" if post_result.exit_code == 0 else "FAIL"
            self.storage.update_attempt(attempt_id, test_status_str, v_status.upper())
            retry_manager.record_attempt(
                attempt_number=attempt_num,
                patch=patch_result,
                verification=verification,
            )

            if v_status == "success":
                print("Repair successfully verified!")
                final_status = RunStatus.SUCCESS
                final_reason = verification.get("evidence", "Repair verified")
                break

            if v_status == "regression":
                # A regression is not something a retry can fix blindly.
                final_status = RunStatus.FAILED
                final_reason = verification.get("evidence", "Regression detected")
                break

            # Both "retry" (partial progress) and "stop" (no progress yet but
            # possibly new evidence) are routed through the retry gate. The
            # gate decides whether another attempt is worthwhile.
            if v_status in ("retry", "stop") and retry_manager.should_retry(
                verification, attempt_number=attempt_num
            ):
                print("Retrying repair with updated diagnostics...")
                self.storage.log_event(
                    run_id, "RETRY_DECISION",
                    f"Retrying after attempt {attempt_num}",
                    metadata={"attempt": attempt_num, "status": v_status},
                )
                current_pre_result = post_result
                continue

            final_status = RunStatus.FAILED
            final_reason = verification.get("evidence", "Repair was not verified")
            break
        else:
            # The retry limit was reached without a verified repair.
            final_status = RunStatus.FAILED
            final_reason = (
                f"The retry limit of {retry_manager.max_retries} attempt(s) was "
                f"reached without a verified repair"
            )

        return self._finish(
            run_id,
            final_status,
            0 if final_status == RunStatus.SUCCESS else 1,
            final_reason,
            final_result=final_result,
            verification=verification,
            attempts=attempt_num,
            baseline_exit_code=baseline_result.exit_code,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_toolchain(
        self, workspace_path: Path
    ) -> Tuple[str, str, List[str], Optional[List[str]]]:
        """Detect language, test framework and the build/test commands."""
        language = self.config.get("language") or self.config.get("FIXPILOT_LANGUAGE", "")
        test_framework = self.config.get("test_framework") or self.config.get(
            "FIXPILOT_TEST_FRAMEWORK", ""
        )
        test_command = self.config.get("test_command") or self.config.get(
            "FIXPILOT_TEST_COMMAND", ""
        )
        build_command = self.config.get("build_command") or self.config.get(
            "FIXPILOT_BUILD_COMMAND", ""
        )

        if not language:
            language = detect_language(workspace_path)
            print(f"Detected language: {language}")

        if not test_framework and language:
            test_framework = detect_test_framework(workspace_path, language)
            print(f"Detected test framework: {test_framework}")

        lang_config = get_language_config(language) if language else None

        if test_command:
            test_cmd = test_command.split() if isinstance(test_command, str) else list(test_command)
        elif lang_config:
            test_cmd = lang_config.get_test_command(test_framework, "")
        else:
            test_cmd = ["python", "-m", "pytest", "-q"]

        if build_command:
            build_cmd = (
                build_command.split()
                if isinstance(build_command, str)
                else list(build_command)
            )
        elif lang_config and lang_config.build_commands:
            build_cmd = lang_config.get_build_command()
        else:
            build_cmd = None

        # Update config for storage
        self.config["language"] = language
        self.config["test_framework"] = test_framework
        self.config["test_command"] = " ".join(test_cmd)
        if build_cmd:
            self.config["build_command"] = " ".join(build_cmd)

        return language, test_framework, test_cmd, build_cmd

    def _build_diagnostics(
        self,
        result: ExecutionResult,
        language: str,
        test_framework: str,
    ) -> Dict[str, Any]:
        """Parse an execution result into structured diagnostics."""
        parser = None
        if language and test_framework:
            parser = PARSER_REGISTRY.get_parser(language, test_framework)

        if parser:
            failures = parser.parse(result.stdout, result.stderr)
            if failures:
                return {
                    "test_output": result.stdout,
                    "stderr": result.stderr,
                    "traceback": failures[0].traceback,
                    "failing_test": failures[0].failing_test,
                    "parsed_failures": failures,
                }
            return {
                "test_output": result.stdout,
                "stderr": result.stderr,
                "traceback": result.stderr or result.stdout,
                "failing_test": "unknown",
                "parsed_failures": [],
            }

        # Fallback to the pytest parser, but say so loudly - a silent
        # fallback would produce "no failures" for every other language.
        print(
            "[!] No diagnostic parser matched "
            f"language='{language}' framework='{test_framework}'. "
            "Falling back to the pytest parser - diagnostics may be incomplete."
        )
        failures = parse_pytest_output(result.stdout, result.stderr)
        if failures:
            return {
                "test_output": result.stdout,
                "stderr": result.stderr,
                "traceback": failures[0].traceback,
                "failing_test": failures[0].failing_test,
                "parsed_failures": failures,
            }
        return {
            "test_output": result.stdout,
            "stderr": result.stderr,
            "traceback": result.stderr or result.stdout,
            "failing_test": "pytest_suite",
            "parsed_failures": [],
        }

    @staticmethod
    def _collect_file_contents(
        workspace_path: Path,
        plan: Any,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Read the current on-disk content of every file the repair needs.

        The files of the repair plan are the primary source. When the plan is
        empty (for example because the investigation produced no usable
        hypothesis) the files referenced by the diagnostics are used instead,
        so the repairer is never asked to work without any context.

        The file names come from the repair plan, which is derived from
        LLM-supplied evidence, so every path is resolved and confined to the
        disposable workspace before it is read. A path that escapes the
        workspace is skipped - it must never be read and shipped to the model.
        """
        contents: Dict[str, str] = {}
        try:
            root = Path(workspace_path).resolve()
        except OSError:
            return contents

        targets = list(getattr(plan, "files_to_change", []) or [])
        if not targets and diagnostics:
            targets = WorkflowEngine._files_from_diagnostics(
                diagnostics, root
            )

        for file_name in targets:
            try:
                target_f = (root / str(file_name)).resolve()
                # Confine the read to the disposable workspace.
                if not target_f.is_relative_to(root):
                    continue
                if target_f.exists() and target_f.is_file():
                    contents[file_name] = target_f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
        return contents

    @staticmethod
    def _files_from_diagnostics(
        diagnostics: Dict[str, Any],
        root: Path,
        limit: int = 3,
    ) -> List[str]:
        """Derive candidate source files from the parsed diagnostics.

        This keeps the repairer useful even when the investigation produced
        no usable hypothesis: the files that the failing tests point at are
        the most likely place of the bug.
        """
        from fixpilot.agents.planner import _map_test_to_source

        candidates: List[str] = []
        for failure in diagnostics.get("parsed_failures", []) or []:
            for reference in getattr(failure, "file_references", []) or []:
                mapped = _map_test_to_source(reference, root)
                if mapped and mapped not in candidates:
                    candidates.append(mapped)
                elif reference and reference not in candidates:
                    candidates.append(reference)

        # Only keep files that really exist inside the workspace.
        existing: List[str] = []
        for candidate in candidates:
            try:
                target = (root / candidate).resolve()
                if target.is_relative_to(root) and target.is_file():
                    existing.append(candidate)
            except (OSError, ValueError):
                continue
        return existing[:limit]

    @staticmethod
    def _ask_for_approval() -> bool:
        """Ask the user to approve a patch.

        A closed stdin (EOF) or a Ctrl+C is treated as a *rejection* - the
        safe default when no human is available to answer.
        """
        try:
            answer = input("Approve and apply this patch? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer.strip().lower() in ("y", "yes")

    @staticmethod
    def _failed_patch_result(exc: Exception):
        """Build an empty PatchResult used to record a failed repair."""
        from fixpilot.schemas.patch import PatchResult

        return PatchResult(
            patch="",
            patch_summary="Repair generation failed",
            rejection_reason=str(exc),
            approval_status="not_requested",
        )

    def _finish(
        self,
        run_id: str,
        status: str,
        exit_code: int,
        reason: str,
        message: Optional[str] = None,
        investigation: Any = None,
        final_result: Optional[ExecutionResult] = None,
        verification: Optional[Dict[str, Any]] = None,
        attempts: int = 0,
        baseline_exit_code: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Persist the final state of a run and build the result payload."""
        self.storage.complete_run(
            run_id,
            status,
            exit_code=exit_code,
            error_summary="" if status == RunStatus.SUCCESS else reason,
        )
        self.storage.update_run_results(
            run_id,
            test_status=self._test_status(final_result),
            test_exit_code=final_result.exit_code if final_result else None,
            test_output=(
                (final_result.stdout or "")[-20000:] if final_result else ""
            ),
            attempt_count=attempts,
            baseline_exit_code=baseline_exit_code,
            retry_count=max(attempts - 1, 0),
        )
        self.storage.log_event(
            run_id, "FINALIZE_REPORT",
            f"Run finished with status {status}",
            level="INFO" if status == RunStatus.SUCCESS else "WARNING",
            metadata={"status": status, "attempts": attempts},
        )

        report = self.storage.export_report(run_id)
        report_path = self.storage.save_report(run_id)
        if report_path:
            print(f"Report saved to: {report_path.resolve()}")
        print("\n" + "=" * 60)
        print(f"FixPilot run {run_id} finished with status: {status}")
        if reason and status != RunStatus.SUCCESS:
            print(f"Reason: {reason}")
        print("=" * 60)

        result: Dict[str, Any] = {
            "run_id": run_id,
            "status": status,
            "reason": reason,
            "report": report,
            "report_path": str(report_path) if report_path else None,
            "attempts": attempts,
        }
        if message:
            result["message"] = message
        if investigation is not None:
            result["investigation"] = investigation
        if verification:
            result["verification"] = verification
        if final_result is not None:
            result["test_output"] = final_result.stdout
            result["test_exit_code"] = final_result.exit_code
        return result

    @staticmethod
    def _test_status(result: Optional[ExecutionResult]) -> str:
        """Map an execution result onto a persisted test status."""
        if result is None:
            return "NOT_RUN"
        if result.timed_out:
            return "TIMEOUT"
        if result.exit_code == 0:
            return "PASS"
        if result.exit_code == -1:
            return "ERROR"
        return "FAIL"
