"""FixPilot AI GitHub repository fetcher.

Responsibilities:
- Clone GitHub repositories via HTTPS or SSH
- Support private repositories via PAT (GITHUB_TOKEN)
- Checkout specific branches or commits
- Handle authentication and common errors
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class CloneError(Exception):
    """Raised when repository cloning fails."""
    pass


class GitHubFetcher:
    """Fetch and clone GitHub repositories."""

    def __init__(self, github_token: str = ""):
        """Initialize the fetcher.

        Args:
            github_token: GitHub Personal Access Token for private repos.
        """
        self.github_token = github_token

    def clone(
        self,
        url: str,
        target: Optional[str] = None,
        branch: Optional[str] = None,
        commit: Optional[str] = None,
        force: bool = False,
    ) -> Path:
        """Clone a GitHub repository.

        Args:
            url: GitHub repository URL (HTTPS or SSH)
            target: Target directory name (default: repo name from URL)
            branch: Branch to checkout (default: default branch)
            commit: Commit SHA to checkout (takes precedence over branch)
            force: Overwrite an existing target directory.

        Returns:
            Path to the cloned repository.

        Raises:
            CloneError: If cloning fails.
        """
        # Parse URL to get repo name
        repo_name = self._extract_repo_name(url)
        if not target:
            target = repo_name

        # Prepare target directory. Never silently delete an existing
        # directory - that is data loss.
        target_path = Path.cwd() / target
        if target_path.exists():
            if not force:
                raise CloneError(
                    f"Target directory '{target_path}' already exists. "
                    "Pass --force to overwrite it, or choose another target."
                )
            shutil.rmtree(target_path)

        # Authenticate without writing the token into the clone's .git/config.
        clone_url = url
        auth_env = None
        if self._needs_token(url):
            auth_env = self._auth_env()

        # Clone the repository
        result = self._run_git(
            ["clone", "--depth", "1", clone_url, str(target_path)],
            check=False,
            env=auth_env,
        )
        if result.returncode != 0:
            # Retry without --depth for repos with submodules or large history.
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
            result = self._run_git(
                ["clone", clone_url, str(target_path)],
                check=False,
                env=auth_env,
            )
            if result.returncode != 0:
                raise CloneError(
                    f"Failed to clone repository: "
                    f"{(result.stderr or result.stdout or 'unknown error').strip()}"
                )

        if not target_path.is_dir():
            raise CloneError(f"Clone reported success but '{target_path}' does not exist.")

        # Checkout specific branch if requested
        if branch:
            try:
                self._run_git(["-C", str(target_path), "checkout", branch], check=True)
            except subprocess.CalledProcessError as e:
                raise CloneError(f"Failed to checkout branch '{branch}': {e}")

        # Checkout specific commit if requested
        if commit:
            try:
                self._run_git(["-C", str(target_path), "checkout", commit], check=True)
            except subprocess.CalledProcessError as e:
                raise CloneError(f"Failed to checkout commit '{commit}': {e}")

        return target_path

    def _extract_repo_name(self, url: str) -> str:
        """Extract repository name from GitHub URL."""
        # HTTPS: https://github.com/owner/repo.git or https://github.com/owner/repo
        # SSH: git@github.com:owner/repo.git
        patterns = [
            r"github\.com/([\w-]+)/([\w.-]+?)(?:\.git)?/?$",
            r"github\.com:([\w-]+)/([\w.-]+?)(?:\.git)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(2)
        return "repo"

    def _needs_token(self, url: str) -> bool:
        """Return True when the URL is HTTPS and a token is available."""
        return bool(self.github_token) and url.startswith("https://")

    def _auth_env(self) -> dict:
        """Build the environment used to authenticate the git request.

        The token is passed through an ``Authorization`` header rather than
        being embedded in the remote URL, so it is never written into the
        clone's ``.git/config``.
        """
        env = os.environ.copy()
        basic = _basic_auth_header(self.github_token)
        if basic:
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraheader"
            env["GIT_CONFIG_VALUE_0"] = basic
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def _prepare_clone_url(self, url: str) -> str:
        """Return the URL to clone from.

        The token is never injected into the URL - that would persist it in
        the clone's ``.git/config`` in plaintext.
        """
        return url

    def _run_git(
        self, args: list, check: bool = True, env: Optional[dict] = None
    ) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result


def _basic_auth_header(token: str) -> str:
    """Build a Basic Authorization header value from a GitHub token."""
    import base64

    if not token:
        return ""
    encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return f"Authorization: Basic {encoded}"
