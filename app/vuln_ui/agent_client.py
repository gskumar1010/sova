# app/vuln_ui/agent_client.py
"""Bridge between the Streamlit UI and the sandboxed OpenCode agent.

Delivers vulnerability scanning prompts via `openshell sandbox exec -- opencode run`,
so every agent invocation runs under the OpenShell policy proxy inside the Kata VM.
"""
import os
import re
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

BLOCKED_RE = re.compile(r"policy_denied|egress.*blocked|connection refused|host not allowed", re.IGNORECASE)

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


def run_agent(prompt: str, scan_id: str = "") -> AgentResult:
    """Execute the vulnerability scanning agent using OpenShell Python API."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        from openshell.sandbox import SandboxClient
    except ImportError as e:
        raise RuntimeError(f"openshell package not installed: {e}")

    sandbox_name = os.environ.get("SANDBOX_NAME", "opencode-dual")
    gateway_endpoint = os.environ.get("OPENSHELL_GATEWAY_ENDPOINT", "http://openshell-kata:8080")
    timeout = int(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "120"))
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")

    logger.info(f"run_agent: sandbox={sandbox_name}, timeout={timeout}s, prompt_len={len(prompt)}")

    # Parse gateway endpoint (format: http://host:port or https://host:port)
    # Extract host:port for gRPC connection
    parsed = urlparse(gateway_endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    endpoint = f"{host}:{port}"

    # Create client with plaintext connection (auth.mode=none)
    client = SandboxClient(
        endpoint=endpoint,
        tls=None,  # Plaintext connection
        bearer_token=None,  # No auth
        timeout=float(timeout)
    )

    try:
        # Execute command in existing sandbox
        # Command: opencode run <prompt>
        env_overrides = {}
        if scan_id:
            env_overrides["SCAN_ID"] = scan_id

        result = client.exec(
            sandbox=sandbox_name,
            command=["opencode", "run", prompt],
            workspace=workspace,
            timeout_seconds=timeout,
            no_login_shell=True,
            env=env_overrides or None,
        )

        # Extract output - result.stdout and result.stderr are already strings
        stdout = result.stdout if result.stdout else ""
        stderr = result.stderr if result.stderr else ""
        raw = stdout + stderr

        logger.info(f"Agent completed: exit_code={result.exit_code}, stdout_len={len(stdout)}, stderr_len={len(stderr)}")

        # Check exit code - if non-zero, prepend error message
        if result.exit_code != 0:
            error_msg = f"⚠️ OpenCode exited with code {result.exit_code}\n\n"
            if result.exit_code == 124:
                error_msg += "**Agent timed out** (exceeded 10 minute limit)\n\n"
            elif result.exit_code == 1:
                error_msg += "**Agent encountered an error**\n\n"
            raw = error_msg + raw

        # Check for blocking
        blocked = bool(BLOCKED_RE.search(raw))
        text = _clean(stdout) if stdout.strip() else _clean(raw)

        # If cleaned text is empty but we have raw output, use raw
        if not text.strip() and raw.strip():
            text = f"**Debug: Cleaned output was empty, showing raw output:**\n\n{raw[:2000]}"

        # Try to extract SARIF data if present in output
        sarif_data = None
        try:
            json_match = re.search(r'\{[^{}]*"version"\s*:\s*"2\.1\.0"[^{}]*\}', raw, re.DOTALL)
            if json_match:
                sarif_data = json.loads(json_match.group(0))
        except (json.JSONDecodeError, AttributeError):
            pass

        return AgentResult(text=text, egress_blocked=blocked, raw=raw, sarif_data=sarif_data)

    finally:
        client.close()
