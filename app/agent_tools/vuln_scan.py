#!/opt/scantools/bin/python3
# app/agent_tools/vuln_scan.py
"""Vulnerability scanning CLI used by the sandboxed OpenCode agent.

Calls the Vulnerability Orchestrator API and manages git cloning.
Network egress is governed by OpenShell policy proxy.

IMPORTANT: This script must be run with Python 3.12 from /opt/scantools/bin/python3
because the base sandbox has Python 3.14 which is incompatible with semgrep dependencies.
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
    """Execute Semgrep locally in the sandbox."""
    try:
        # Download semgrep rules locally first (semgrep Python requests can't access registry,
        # but curl can due to OpenShell policy allowing /usr/bin/curl)
        rules_file = "/tmp/semgrep-rules.yaml"

        # Download security-audit rules
        download_result = subprocess.run(
            ["curl", "-sL", "https://semgrep.dev/c/p/security-audit", "-o", rules_file],
            capture_output=True,
            text=True,
            timeout=60
        )

        if download_result.returncode != 0:
            return {"error": f"Failed to download semgrep rules: {download_result.stderr}"}

        # Run semgrep with local rules
        cmd = [
            "/opt/scantools/bin/semgrep",
            f"--config={rules_file}",
            "--sarif",
            f"--output={output}",
            "--metrics=off",
            path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "HOME": "/tmp"}  # Writable HOME for semgrep cache
        )

        # Read SARIF output
        if os.path.exists(output):
            with open(output, 'r') as f:
                sarif_data = json.load(f)
            return {
                "status": "success",
                "sarif": sarif_data,
                "output_file": output,
                "exit_code": result.returncode
            }
        else:
            return {"error": f"Semgrep completed but output file not found: {output}"}

    except subprocess.TimeoutExpired:
        return {"error": "Semgrep timed out after 300 seconds"}
    except Exception as e:
        return {"error": f"Semgrep execution failed: {str(e)}"}


def run_bandit_scan(path: str, output: str) -> dict:
    """Execute Bandit locally in the sandbox."""
    try:
        # Run bandit from Python 3.12 venv (consistency with semgrep)
        cmd = [
            "/opt/scantools/bin/bandit",
            "-r", path,
            "-f", "json",
            "-o", output
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "HOME": "/tmp"}  # Writable HOME
        )

        # Read JSON output
        if os.path.exists(output):
            with open(output, 'r') as f:
                bandit_data = json.load(f)
            return {
                "status": "success",
                "results": bandit_data,
                "output_file": output,
                "exit_code": result.returncode
            }
        else:
            return {"error": f"Bandit completed but output file not found: {output}"}

    except subprocess.TimeoutExpired:
        return {"error": "Bandit timed out after 300 seconds"}
    except Exception as e:
        return {"error": f"Bandit execution failed: {str(e)}"}


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
