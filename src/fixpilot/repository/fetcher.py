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
import tempfile
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
    ) -> Path:
        """Clone a GitHub repository.

        Args:
            url: GitHub repository URL (HTTPS or SSH)
            target: Target directory name (default: repo name from URL)
            branch: Branch to checkout (default: default branch)
            commit: Commit SHA to checkout (takes precedence over branch)

        Returns:
            Path to the cloned repository.

        Raises:
            CloneError: If cloning fails.
        """
        # Parse URL to get repo name and prepare authenticated URL
        repo_name = self._extract_repo_name(url)
        if not target:
            target = repo_name

        # Prepare target directory
        target_path = Path.cwd() / target
        if target_path.exists():
            # Remove existing directory
            shutil.rmtree(target_path)

        # Prepare authenticated URL for HTTPS
        clone_url = self._prepare_clone_url(url)

        # Clone the repository
        try:
            self._run_git(["clone", "--depth", "1", clone_url, str(target_path)], check=False)
        except subprocess.CalledProcessError as e:
            # Try without --depth for repos with submodules or large history
            try:
                self._run_git(["clone", clone_url, str(target_path)], check=True)
            except subprocess.CalledProcessError as e2:
                raise CloneError(f"Failed to clone repository: {e2}")

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

    def _prepare_clone_url(self, url: str) -> str:
        """Prepare authenticated clone URL for HTTPS."""
        # If it's already SSH, return as-is (assumes SSH keys are set up)
        if url.startswith("git@github.com:"):
            return url

        # If it's HTTPS and we have a token, inject it
        if self.github_token and url.startswith("https://github.com/"):
            # Format: https://<token>@github.com/owner/repo.git
            return url.replace("https://github.com/", f"https://{self.github_token}@github.com/")

        return url

    def _run_git(self, args: list, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
        return result