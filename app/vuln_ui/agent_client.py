# app/vuln_ui/agent_client.py
"""Bridge between the Streamlit UI and the sandboxed OpenCode agent.

Delivers vulnerability scanning prompts via `openshell sandbox exec -- opencode run`,
so every agent invocation runs under the OpenShell policy proxy inside the Kata VM.
"""
import os
import re
import subprocess
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

BLOCKED_RE = re.compile(r"policy_denied|blocked|connection refused|denied", re.IGNORECASE)

# Allowlisted git hosting domains
ALLOWED_GIT_HOSTS = ["github.com", "gitlab.com", "bitbucket.org"]


def _clean(text: str) -> str:
    """Tidy OpenCode/gemma output for display.

    Strips OpenCode's "> build · model" header and gemma's harmony "channel"
    delimiters (e.g. <|channel>thought<channel|>). When the harmony final
    channel marker is present, keep only the text after the last one - that is
    the model's final answer, not its intermediate tool trace.
    """
    t = text
    t = re.sub(r"(?m)^\s*>\s*build\b.*$", "", t)
    if "<channel|>" in t:
        t = t.rsplit("<channel|>", 1)[-1]
    # Remove any residual harmony tokens like <|channel>thought, <|start|>, etc.
    t = re.sub(r"<\|?[^>\n]*\|?>", "", t)
    return t.strip()


def validate_git_url(git_url: str) -> tuple[bool, str]:
    """
    Validate git repository URL for security.

    Returns:
        (is_valid, error_message)
    """
    try:
        parsed = urlparse(git_url)

        # Check for valid scheme
        if parsed.scheme not in ["http", "https"]:
            return False, "Only HTTP/HTTPS URLs are allowed"

        # Check for allowlisted hosts
        if parsed.hostname not in ALLOWED_GIT_HOSTS:
            return False, f"Only {', '.join(ALLOWED_GIT_HOSTS)} are allowed"

        # Basic path validation
        if not parsed.path or parsed.path == "/":
            return False, "Invalid repository path"

        return True, ""

    except Exception as e:
        return False, f"Invalid URL: {str(e)}"


def parse_sarif(sarif_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key metrics from SARIF output.

    Returns:
        Dict with vulnerability counts and findings
    """
    findings = []
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for run in sarif_data.get("runs", []):
        tool_name = run.get("tool", {}).get("driver", {}).get("name", "Unknown")

        for result in run.get("results", []):
            level = result.get("level", "note")
            rule_id = result.get("ruleId", "UNKNOWN")
            message = result.get("message", {}).get("text", "")

            # Map SARIF level to severity
            severity_map = {
                "error": "critical" if "critical" in message.lower() or "CWE-89" in rule_id or "injection" in message.lower() else "high",
                "warning": "medium",
                "note": "low"
            }
            severity = severity_map.get(level, "low")
            severity_counts[severity] += 1

            # Extract location info
            locations = result.get("locations", [])
            file_path = "unknown"
            line_number = 0
            snippet = ""

            if locations:
                loc = locations[0].get("physicalLocation", {})
                file_path = loc.get("artifactLocation", {}).get("uri", "unknown")
                region = loc.get("region", {})
                line_number = region.get("startLine", 0)
                snippet = region.get("snippet", {}).get("text", "")

            findings.append({
                "tool": tool_name,
                "rule_id": rule_id,
                "severity": severity,
                "message": message,
                "file": file_path,
                "line": line_number,
                "snippet": snippet
            })

    return {
        "total": sum(severity_counts.values()),
        "severity_counts": severity_counts,
        "findings": findings
    }


@dataclass
class AgentResult:
    text: str
    egress_blocked: bool
    raw: str
    sarif_data: Optional[Dict[str, Any]] = None


def run_agent(prompt: str) -> AgentResult:
    """Execute the vulnerability scanning agent."""
    sandbox = os.environ.get("SANDBOX_NAME", "opencode-dual")
    timeout = int(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "120"))

    cmd = [
        "openshell", "sandbox", "exec", "-n", sandbox, "--no-tty",
        "--timeout", str(timeout), "--", "opencode", "run", prompt,
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    raw = (proc.stdout or "") + (proc.stderr or "")
    blocked = bool(BLOCKED_RE.search(raw))
    text = _clean(proc.stdout) if proc.stdout.strip() else _clean(raw)

    # Try to extract SARIF data if present in output
    sarif_data = None
    try:
        # Look for JSON in output that might be SARIF
        json_match = re.search(r'\{[^{}]*"version"\s*:\s*"2\.1\.0"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            sarif_data = json.loads(json_match.group(0))
    except (json.JSONDecodeError, AttributeError):
        pass

    return AgentResult(text=text, egress_blocked=blocked, raw=raw, sarif_data=sarif_data)
