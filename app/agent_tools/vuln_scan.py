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
from typing import Optional

import requests
import git

# Import code graph functionality
try:
    from code_graph import build_graph_cli, analyze_reachability_cli
    CODE_GRAPH_AVAILABLE = True
except ImportError:
    CODE_GRAPH_AVAILABLE = False

# Port 8080 is required: the OpenShell egress policy allowlists
# vuln-orchestrator-api:8080 exactly. Any other port is denied.
DEFAULT_BASE = "http://vuln-orchestrator-api:8080"
MAX_REPO_SIZE_MB = 500
CLONE_TIMEOUT = 300


def base_url() -> str:
    return os.environ.get("VULN_API_URL", DEFAULT_BASE).rstrip("/")


def report_progress(step: str, status: str, detail: str = None) -> None:
    """Fire-and-forget progress ping to the orchestrator."""
    scan_id = os.environ.get("SCAN_ID", "")
    if not scan_id:
        return
    try:
        payload = {"step": step, "status": status}
        if detail:
            payload["detail"] = detail
        requests.post(
            f"{base_url()}/scan/progress/{scan_id}",
            json=payload,
            timeout=5,
        )
    except Exception:
        pass  # never fail a scan because of a progress ping


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
    """Execute Semgrep locally in the sandbox with multiple rulesets."""
    try:
        # Download semgrep rules locally first (semgrep Python requests can't access registry,
        # but curl can due to OpenShell policy allowing /usr/bin/curl)

        # Download multiple rulesets for comprehensive coverage
        rulesets = [
            ("https://semgrep.dev/c/p/security-audit", "/tmp/semgrep-security-audit.yaml"),
            ("https://semgrep.dev/c/p/python", "/tmp/semgrep-python.yaml"),
            ("https://semgrep.dev/c/p/owasp-top-ten", "/tmp/semgrep-owasp.yaml"),
        ]

        downloaded_rules = []
        for url, filepath in rulesets:
            download_result = subprocess.run(
                ["curl", "-sL", url, "-o", filepath],
                capture_output=True,
                text=True,
                timeout=60
            )

            if download_result.returncode == 0 and os.path.exists(filepath):
                downloaded_rules.append(filepath)
            # Continue even if one ruleset fails to download

        if not downloaded_rules:
            return {"error": "Failed to download any semgrep rulesets"}

        # Run semgrep with all downloaded rulesets
        cmd = [
            "/opt/scantools/bin/semgrep",
            "--sarif",
            f"--output={output}",
            "--metrics=off",
        ]

        # Add all downloaded rule configs
        for rule_file in downloaded_rules:
            cmd.append(f"--config={rule_file}")

        cmd.append(path)

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


def filter_sarif_by_reachability(sarif_path: str, graph_path: str, output_path: str) -> dict:
    """Filter SARIF results by reachability analysis."""
    try:
        # Load SARIF
        with open(sarif_path, 'r') as f:
            sarif_data = json.load(f)

        # Load code graph
        with open(graph_path, 'r') as f:
            graph_dict = json.load(f)

        if not CODE_GRAPH_AVAILABLE:
            return {"error": "Code graph module not available"}

        from code_graph import CodeGraph, FileNode, ReachabilityAnalyzer

        # Reconstruct CodeGraph
        files = {
            path: FileNode(**node_dict)
            for path, node_dict in graph_dict["files"].items()
        }

        graph = CodeGraph(
            files=files,
            entry_points=graph_dict["entry_points"],
            import_map=graph_dict["import_map"],
            function_map=graph_dict["function_map"],
            call_graph=graph_dict["call_graph"]
        )

        analyzer = ReachabilityAnalyzer(graph)

        # Filter SARIF results
        reachable_results = []
        unreachable_results = []
        stats = {
            "total": 0,
            "reachable": 0,
            "unreachable": 0,
            "unknown": 0
        }

        for run in sarif_data.get("runs", []):
            filtered_results = []

            for result in run.get("results", []):
                stats["total"] += 1

                # Extract file path from result
                locations = result.get("locations", [])
                if not locations:
                    # No location info, keep it
                    filtered_results.append(result)
                    stats["unknown"] += 1
                    continue

                loc = locations[0].get("physicalLocation", {})
                file_path = loc.get("artifactLocation", {}).get("uri", "")

                if not file_path:
                    filtered_results.append(result)
                    stats["unknown"] += 1
                    continue

                # Analyze reachability
                analysis = analyzer.analyze_vulnerability(file_path)

                if analysis["reachable"]:
                    # Add reachability annotation to result
                    if "properties" not in result:
                        result["properties"] = {}
                    result["properties"]["reachability"] = {
                        "reachable": True,
                        "confidence": analysis["confidence"],
                        "reason": analysis["reason"],
                        "call_chain": analysis["call_chain"]
                    }
                    filtered_results.append(result)
                    reachable_results.append(result)
                    stats["reachable"] += 1
                else:
                    # Store in unreachable list for separate report
                    if "properties" not in result:
                        result["properties"] = {}
                    result["properties"]["reachability"] = {
                        "reachable": False,
                        "confidence": analysis["confidence"],
                        "reason": analysis["reason"]
                    }
                    unreachable_results.append(result)
                    stats["unreachable"] += 1

            # Update run with filtered results
            run["results"] = filtered_results

        # Save filtered SARIF
        with open(output_path, 'w') as f:
            json.dump(sarif_data, f, indent=2)

        # Save unreachable findings separately
        unreachable_path = output_path.replace('.sarif', '_unreachable.sarif')
        unreachable_sarif = {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "tool": sarif_data["runs"][0]["tool"] if sarif_data.get("runs") else {},
                "results": unreachable_results
            }]
        }
        with open(unreachable_path, 'w') as f:
            json.dump(unreachable_sarif, f, indent=2)

        return {
            "status": "success",
            "output_file": output_path,
            "unreachable_file": unreachable_path,
            "stats": stats,
            "reduction_percentage": round((stats["unreachable"] / stats["total"] * 100) if stats["total"] > 0 else 0, 1)
        }

    except FileNotFoundError as e:
        return {"error": f"File not found: {str(e)}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {str(e)}"}
    except Exception as e:
        return {"error": f"Filter failed: {str(e)}"}


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

    # Build-graph subcommand (NEW - for reachability analysis)
    p_graph = sub.add_parser("build-graph", help="Build code graph for reachability analysis")
    p_graph.add_argument("--path", required=True, help="Path to repository")
    p_graph.add_argument("--output", required=True, help="Output JSON file for graph")

    # Analyze-reachability subcommand (NEW)
    p_reach = sub.add_parser("analyze-reachability", help="Analyze if vulnerability is reachable")
    p_reach.add_argument("--graph", required=True, help="Code graph JSON file")
    p_reach.add_argument("--file", required=True, help="Vulnerable file path")
    p_reach.add_argument("--function", help="Vulnerable function name (optional)")

    # Filter-sarif subcommand (NEW - filter SARIF by reachability)
    p_filter = sub.add_parser("filter-sarif", help="Filter SARIF results by reachability")
    p_filter.add_argument("--sarif", required=True, help="Input SARIF file")
    p_filter.add_argument("--graph", required=True, help="Code graph JSON file")
    p_filter.add_argument("--output", required=True, help="Output filtered SARIF file")

    args = parser.parse_args(argv)

    try:
        if args.command == "clone":
            report_progress("clone", "started")
            result = clone_repo(args.url, args.dest)
            status = "failed" if "error" in result else "completed"
            detail = f"{result.get('size_mb', '')} MB · {result.get('commit', '')}" if status == "completed" else result.get("error")
            report_progress("clone", status, detail)
        elif args.command == "semgrep":
            report_progress("semgrep", "started")
            result = run_semgrep_scan(args.path, args.output)
            if "error" in result:
                report_progress("semgrep", "failed", result["error"])
            else:
                count = len(result.get("sarif", {}).get("runs", [{}])[0].get("results", []))
                report_progress("semgrep", "completed", f"{count} findings")
        elif args.command == "bandit":
            report_progress("bandit", "started")
            result = run_bandit_scan(args.path, args.output)
            if "error" in result:
                report_progress("bandit", "failed", result["error"])
            else:
                count = len(result.get("results", {}).get("results", []))
                report_progress("bandit", "completed", f"{count} findings")
        elif args.command == "safety":
            result = run_safety_scan(args.requirements)
        elif args.command == "report":
            report_progress("analysis", "completed")
            result = submit_report(args.scan_id, args.sarif)
        elif args.command == "build-graph":
            if not CODE_GRAPH_AVAILABLE:
                result = {"error": "Code graph module not available"}
            else:
                result = build_graph_cli(args.path, args.output)
        elif args.command == "analyze-reachability":
            if not CODE_GRAPH_AVAILABLE:
                result = {"error": "Code graph module not available"}
            else:
                result = analyze_reachability_cli(args.graph, args.file,
                                                  args.function if hasattr(args, 'function') else None)
        elif args.command == "filter-sarif":
            result = filter_sarif_by_reachability(args.sarif, args.graph, args.output)
        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result))
        return 0 if "error" not in result else 1

    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
