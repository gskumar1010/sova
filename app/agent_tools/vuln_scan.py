# app/agent_tools/vuln_scan.py
"""Vulnerability scanning CLI used by the sandboxed OpenCode agent.

Calls the Vulnerability Orchestrator API and manages git cloning.
Network egress is governed by OpenShell policy proxy.
"""
import argparse
import json
import os
import sys
import subprocess
import shlex
from pathlib import Path

import requests
import git

# Port 8080 is required: the OpenShell egress policy allowlists
# vuln-orchestrator-api:8080 exactly. Any other port is denied.
DEFAULT_BASE = "http://vuln-orchestrator-api:8080"
MAX_REPO_SIZE_MB = 500
CLONE_TIMEOUT = 300


def base_url() -> str:
    return os.environ.get("VULN_API_URL", DEFAULT_BASE).rstrip("/")


def clone_repo(git_url: str, dest: str) -> dict:
    """
    Safely clone a git repository with security constraints.

    Args:
        git_url: Repository URL to clone
        dest: Destination directory

    Returns:
        Dict with status and details
    """
    try:
        # Validate URL accessibility first (without cloning)
        try:
            git.cmd.Git().ls_remote(git_url)
        except Exception as e:
            return {"error": f"Repository not accessible: {str(e)}"}

        # Disable git hooks for security
        env = os.environ.copy()
        env['GIT_CONFIG_GLOBAL'] = '/dev/null'
        env['GIT_CONFIG_SYSTEM'] = '/dev/null'

        # Perform shallow clone with depth=1
        repo = git.Repo.clone_from(
            git_url,
            dest,
            depth=1,
            single_branch=True,
            env=env
        )

        # Check repository size
        repo_size_mb = sum(f.stat().st_size for f in Path(dest).rglob('*') if f.is_file()) / (1024 * 1024)
        if repo_size_mb > MAX_REPO_SIZE_MB:
            return {"error": f"Repository too large: {repo_size_mb:.1f}MB (max {MAX_REPO_SIZE_MB}MB)"}

        return {
            "status": "success",
            "path": dest,
            "size_mb": round(repo_size_mb, 2),
            "commit": repo.head.commit.hexsha[:8]
        }

    except Exception as e:
        return {"error": f"Clone failed: {str(e)}"}


def run_semgrep_scan(path: str, output: str) -> dict:
    """Execute Semgrep via orchestrator API."""
    try:
        resp = requests.post(
            f"{base_url()}/tools/semgrep",
            json={"path": path, "output": output},
            timeout=320  # Slightly longer than scanner timeout
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": f"Semgrep API call failed: {str(e)}"}


def run_bandit_scan(path: str, output: str) -> dict:
    """Execute Bandit via orchestrator API."""
    try:
        resp = requests.post(
            f"{base_url()}/tools/bandit",
            json={"path": path, "output": output},
            timeout=320
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": f"Bandit API call failed: {str(e)}"}


def run_safety_scan(requirements_file: str) -> dict:
    """Execute Safety via orchestrator API."""
    try:
        resp = requests.post(
            f"{base_url()}/tools/safety",
            json={"requirements_file": requirements_file},
            timeout=70
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": f"Safety API call failed: {str(e)}"}


def submit_report(scan_id: str, sarif_path: str) -> dict:
    """Submit SARIF results to orchestrator."""
    try:
        with open(sarif_path, 'r') as f:
            sarif_content = f.read()

        resp = requests.post(
            f"{base_url()}/scan/results/{scan_id}",
            json={"sarif_content": sarif_content},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except FileNotFoundError:
        return {"error": f"SARIF file not found: {sarif_path}"}
    except requests.RequestException as e:
        return {"error": f"Report submission failed: {str(e)}"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Vulnerability scanning toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    # Clone subcommand
    p_clone = sub.add_parser("clone", help="Clone a git repository safely")
    p_clone.add_argument("--url", required=True, help="Git repository URL")
    p_clone.add_argument("--dest", required=True, help="Destination directory")

    # Semgrep subcommand
    p_semgrep = sub.add_parser("semgrep", help="Run Semgrep scanner")
    p_semgrep.add_argument("--path", required=True, help="Path to scan")
    p_semgrep.add_argument("--output", required=True, help="Output SARIF file")

    # Bandit subcommand
    p_bandit = sub.add_parser("bandit", help="Run Bandit scanner")
    p_bandit.add_argument("--path", required=True, help="Path to scan")
    p_bandit.add_argument("--output", required=True, help="Output JSON file")

    # Safety subcommand
    p_safety = sub.add_parser("safety", help="Check dependency vulnerabilities")
    p_safety.add_argument("--requirements", required=True, help="requirements.txt path")

    # Report subcommand
    p_report = sub.add_parser("report", help="Submit scan results")
    p_report.add_argument("--scan-id", required=True, help="Scan ID")
    p_report.add_argument("--sarif", required=True, help="SARIF file path")

    args = parser.parse_args(argv)

    try:
        if args.command == "clone":
            result = clone_repo(args.url, args.dest)
        elif args.command == "semgrep":
            result = run_semgrep_scan(args.path, args.output)
        elif args.command == "bandit":
            result = run_bandit_scan(args.path, args.output)
        elif args.command == "safety":
            result = run_safety_scan(args.requirements)
        elif args.command == "report":
            result = submit_report(args.scan_id, args.sarif)
        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result))
        return 0 if "error" not in result else 1

    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
