"""FixPilot AI Workflow Engine.

Orchestrates the autonomous debugging and self-healing lifecycle:
Scan -> Baseline -> Diagnostics -> Investigation -> Planning -> Patching -> Approval -> Verification -> Storage/Report.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fixpilot.config import get_config
from fixpilot.scanner.project_scanner import scan_project
from fixpilot.sandbox.docker_executor import DockerExecutor, DockerUnavailableError
from fixpilot.diagnostics import parse_pytest_output, parse_traceback, redact_sensitive_data, PARSER_REGISTRY
from fixpilot.llm.provider import BaseLLMProvider, GeminiProvider
from fixpilot.agents.investigator import Investigator
from fixpilot.agents.planner import Planner
from fixpilot.agents.repairer import Repairer
from fixpilot.agents.verifier import Verifier
from fixpilot.agents.retry_manager import RetryManager
from fixpilot.patching.validator import PatchApplier, PatchValidationError
from fixpilot.storage.database import Storage
from fixpilot.schemas.execution import ExecutionResult
from fixpilot.reporting.markdown_report import generate_markdown_report
from fixpilot.languages import detect_language, detect_test_framework, get_language_config


class LocalExecutor:
    """Local test executor for development or fallback environments."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.timeout_seconds = self.config.get("FIXPILOT_TIMEOUT_SECONDS", 120)

    def run_tests(
        self,
        test_command: List[str],
        workspace_path: Path,
        language: str = None,
        build_command: List[str] = None,
    ) -> ExecutionResult:
        import subprocess
        import time

        # Run build command first if provided
        if build_command:
            start_time = time.time()
            try:
                build_result = subprocess.run(
                    build_command,
                    cwd=str(workspace_path),
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
                build_duration = round(time.time() - start_time, 3)
                if build_result.returncode != 0:
                    return ExecutionResult(
                        exit_code=build_result.returncode,
                        stdout=build_result.stdout.decode("utf-8", errors="replace"),
                        stderr=build_result.stderr.decode("utf-8", errors="replace"),
                        timed_out=False,
                        duration=build_duration,
                        sandbox_id="local",
                    )
            except subprocess.TimeoutExpired:
                build_duration = round(time.time() - start_time, 3)
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=f"Build timed out after {self.timeout_seconds}s",
                    timed_out=True,
                    duration=build_duration,
                    sandbox_id="local",
                )
            except Exception as e:
                build_duration = round(time.time() - start_time, 3)
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    timed_out=False,
                    duration=build_duration,
                    sandbox_id="local",
                )

        # Run the test command
        cmd = test_command if test_command else ["python", "-m", "pytest", "-q"]
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace_path),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=result.returncode,
                stdout=result.stdout.decode("utf-8", errors="replace"),
                stderr=result.stderr.decode("utf-8", errors="replace"),
                timed_out=False,
                duration=duration,
                sandbox_id="local",
            )
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Local execution timed out after {self.timeout_seconds}s",
                timed_out=True,
                duration=duration,
                sandbox_id="local",
            )
        except Exception as e:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                duration=duration,
                sandbox_id="local",
            )


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
                    self.llm_provider = GeminiProvider(api_key=api_key, model=self.config.get("FIXPILOT_MODEL", "gemini-1.5-flash"))
                except Exception:
                    self.llm_provider = None
            else:
                self.llm_provider = None

        # Sandbox / Runner setup
        if executor:
            self.executor = executor
        else:
            docker_exec = DockerExecutor(self.config)
            if docker_exec._check_docker_available():
                self.executor = docker_exec
            elif self.config.get("FIXPILOT_ALLOW_LOCAL_RUNNER", True):
                self.executor = LocalExecutor(self.config)
            else:
                self.executor = docker_exec

    def execute(
        self,
        project_path: Path,
        analysis_only: bool = False,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """Execute the full repair workflow on a target project."""
        project_path = Path(project_path).resolve()
        if not project_path.is_dir():
            raise ValueError(f"Project directory does not exist: {project_path}")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.storage.start_run(run_id, {"target_path": str(project_path), "mode": "analysis" if analysis_only else "repair"})

        # Create isolated disposable copy so original project is untouched
        temp_dir = tempfile.mkdtemp(prefix="fixpilot_work_")
        workspace_path = Path(temp_dir)
        try:
            shutil.copytree(project_path, workspace_path, dirs_exist_ok=True)
            return self._run_pipeline(
                run_id=run_id,
                project_path=project_path,
                workspace_path=workspace_path,
                analysis_only=analysis_only,
                auto_approve=auto_approve,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_pipeline(
        self,
        run_id: str,
        project_path: Path,
        workspace_path: Path,
        analysis_only: bool,
        auto_approve: bool,
    ) -> Dict[str, Any]:
        print(f"\n[1/5] Scanning project: {project_path}")

        # Detect language and test framework
        language = self.config.get("language") or self.config.get("FIXPILOT_LANGUAGE", "")
        test_framework = self.config.get("test_framework") or self.config.get("FIXPILOT_TEST_FRAMEWORK", "")
        test_command = self.config.get("test_command") or self.config.get("FIXPILOT_TEST_COMMAND", "")
        build_command = self.config.get("build_command") or self.config.get("FIXPILOT_BUILD_COMMAND", "")

        if not language:
            language = detect_language(workspace_path)
            print(f"Detected language: {language}")

        if not test_framework and language:
            test_framework = detect_test_framework(workspace_path, language)
            print(f"Detected test framework: {test_framework}")

        # Get language config
        lang_config = get_language_config(language) if language else None

        # Determine test command
        if test_command:
            test_cmd = test_command.split()
        elif lang_config:
            test_cmd = lang_config.get_test_command(test_framework, test_command)
        else:
            test_cmd = ["python", "-m", "pytest", "-q"]

        # Determine build command
        build_cmd = None
        if build_command:
            build_cmd = build_command.split() if isinstance(build_command, str) else list(build_command)
        elif lang_config and lang_config.build_commands:
            build_cmd = lang_config.get_build_command()

        # Update config for storage
        self.config["language"] = language
        self.config["test_framework"] = test_framework
        self.config["test_command"] = " ".join(test_cmd)
        if build_cmd:
            self.config["build_command"] = " ".join(build_cmd)

        scan_info = scan_project(workspace_path, self.config)

        # Run build command if available (via executor)
        if build_cmd:
            print(f"\n[2/6] Running build command: {' '.join(build_cmd)}")
            build_result = self.executor.run_tests(
                build_cmd, workspace_path, language=language, build_command=None
            )
            if build_result.timed_out:
                print("ERROR: Build timed out.")
                self.storage.complete_run(run_id, "FAILED", build_result.exit_code, "Build timed out")
                self.storage.save_report(run_id)
                return {"run_id": run_id, "status": "FAILED", "reason": "Build timed out"}
            if build_result.exit_code != 0:
                print(f"Build failed with exit code: {build_result.exit_code}")
                print(f"Build stderr: {build_result.stderr[:500]}")

        print("\n[3/6] Running baseline tests...")
        baseline_result = self.executor.run_tests(test_cmd, workspace_path, language=language)

        if baseline_result.timed_out:
            print("ERROR: Baseline tests timed out.")
            self.storage.complete_run(run_id, "FAILED", baseline_result.exit_code, "Baseline timed out")
            self.storage.save_report(run_id)
            return {"run_id": run_id, "status": "FAILED", "reason": "Baseline timed out"}

        if baseline_result.exit_code == 0:
            print("Baseline tests passed - no failing tests detected. Nothing to repair.")
            self.storage.complete_run(run_id, "SUCCESS", 0, "No failing tests")
            self.storage.save_report(run_id)
            return {"run_id": run_id, "status": "SUCCESS", "message": "All tests pass"}

        print(f"Detected test failures (exit code: {baseline_result.exit_code})")

        # Diagnostics & Investigation
        print("\n[4/6] Extracting diagnostics & investigating root cause...")

        # Select appropriate diagnostic parser
        parser = None
        if language and test_framework:
            parser = PARSER_REGISTRY.get_parser(language, test_framework)

        if parser:
            failures = parser.parse(baseline_result.stdout, baseline_result.stderr)
            if failures:
                failing_test = failures[0].failing_test
                diagnostics = {
                    "test_output": baseline_result.stdout,
                    "stderr": baseline_result.stderr,
                    "traceback": failures[0].traceback,
                    "failing_test": failing_test,
                    "parsed_failures": failures,
                }
            else:
                diagnostics = {
                    "test_output": baseline_result.stdout,
                    "stderr": baseline_result.stderr,
                    "traceback": baseline_result.stderr or baseline_result.stdout,
                    "failing_test": "unknown",
                }
        else:
            # Fallback to pytest parser
            failures = parse_pytest_output(baseline_result.stdout, baseline_result.stderr)
            if failures:
                failing_test = failures[0].failing_test
                diagnostics = {
                    "test_output": baseline_result.stdout,
                    "stderr": baseline_result.stderr,
                    "traceback": failures[0].traceback,
                    "failing_test": failing_test,
                    "parsed_failures": failures,
                }
            else:
                diagnostics = {
                    "test_output": baseline_result.stdout,
                    "stderr": baseline_result.stderr,
                    "traceback": baseline_result.stderr or baseline_result.stdout,
                    "failing_test": "pytest_suite",
                }

        investigator = Investigator(self.llm_provider)
        investigation = investigator.investigate(
            diagnostics=diagnostics,
            project_metadata={"path": str(workspace_path), "scan": scan_info, "language": language},
            config=self.config,
        )

        print(f"Investigation completed: {len(investigation.root_cause_hypotheses)} hypothesis(es) found.")
        for i, hyp in enumerate(investigation.root_cause_hypotheses, 1):
            print(f"  {i}. {hyp.explanation} (Confidence: {hyp.confidence})")

        if analysis_only:
            print("\nAnalysis-only mode requested. Halting repair workflow.")
            self.storage.complete_run(run_id, "SUCCESS", baseline_result.exit_code, "Analysis completed")
            self.storage.save_report(run_id)
            return {"run_id": run_id, "status": "SUCCESS", "investigation": investigation}

        # Planning
        print("\n[5/6] Creating repair plan...")
        planner = Planner()
        plan = planner.create_plan(investigation, self.config, workspace_path=workspace_path)
        # Add language context to plan
        if hasattr(plan, 'language'):
            plan.language = language
            plan.test_framework = test_framework
        print(f"Plan goal: {plan.goal}")
        print(f"Files to modify: {', '.join(plan.files_to_change) if plan.files_to_change else 'None specified'}")

        # Repair & Verification Loop
        print("\n[6/6] Executing repair and verification loop...")
        repairer = Repairer(llm_provider=self.llm_provider)
        verifier = Verifier()
        retry_manager = RetryManager(self.config, workspace_path=workspace_path)
        applier = PatchApplier(self.config)

        # Build context from workspace files
        file_contents = {}
        for file_name in plan.files_to_change:
            target_f = workspace_path / file_name
            if target_f.exists():
                file_contents[file_name] = target_f.read_text(encoding="utf-8")

        attempt_num = 0
        current_pre_result = baseline_result
        final_status = "FAILED"

        while attempt_num < retry_manager.max_retries:
            attempt_num += 1
            attempt_id = f"att_{run_id}_{attempt_num}"
            print(f"\n--- Attempt {attempt_num}/{retry_manager.max_retries} ---")

            patch_result = repairer.generate_patch(plan, {"file_contents": file_contents, "changed_files": plan.files_to_change})
            self.storage.create_attempt(attempt_id, run_id, attempt_num, patch_result, self.config)

            if not patch_result.patch:
                print("No patch diff generated.")
                self.storage.update_attempt(attempt_id, "NO_PATCH", "STOP")
                break

            # Validate patch
            is_valid, validation_msg = applier.validate_patch(patch_result.patch, workspace_path)
            if not is_valid:
                print(f"Patch validation failed: {validation_msg}")
                self.storage.update_attempt(attempt_id, "INVALID_PATCH", "REJECTED")
                break

            # Approval gate
            approval_required = self.config.get("FIXPILOT_APPROVAL_REQUIRED", True)
            if approval_required and not auto_approve:
                print(f"\nPatch Preview:\n{patch_result.patch}\n")
                ans = input("Approve and apply this patch? [y/N]: ").strip().lower()
                if ans not in ("y", "yes"):
                    print("Patch rejected by user.")
                    self.storage.update_attempt(attempt_id, "ABORTED", "USER_REJECTED")
                    final_status = "REJECTED"
                    break

            # Apply patch
            applied, apply_msg, backup_path = applier.apply_patch(patch_result.patch, workspace_path, create_backup=True)
            if not applied:
                print(f"Failed to apply patch: {apply_msg}")
                self.storage.update_attempt(attempt_id, "APPLY_FAILED", "RETRY")
                continue

            # Run post-patch tests
            post_result = self.executor.run_tests(test_cmd, workspace_path, language=language)
            verification = verifier.verify(current_pre_result, post_result, baseline_result, self.config)
            v_status = verification.get("status", "stop")
            print(f"Verification result: {v_status.upper()} - {verification.get('evidence', '')}")

            test_status_str = "PASS" if post_result.exit_code == 0 else "FAIL"
            self.storage.update_attempt(attempt_id, test_status_str, v_status.upper())

            if v_status == "success":
                print("Repair successfully verified!")
                final_status = "SUCCESS"
                break
            elif v_status in ("retry", "regression"):
                if retry_manager.should_retry(verification):
                    print("Retrying repair with updated diagnostics...")
                    current_pre_result = post_result
                    continue
                else:
                    print("Retry limit reached or non-retryable failure.")
                    break
            else:
                break

        self.storage.complete_run(run_id, final_status, 0 if final_status == "SUCCESS" else 1)
        report = self.storage.export_report(run_id)
        # Auto-save report to reports directory
        report_path = self.storage.save_report(run_id)
        if report_path:
            print(f"Report saved to: {report_path.resolve()}")
        print("\n" + "=" * 60)
        print(f"FixPilot run {run_id} finished with status: {final_status}")
        print("=" * 60)
        return {"run_id": run_id, "status": final_status, "report": report, "report_path": str(report_path) if report_path else None}
