# app/vuln_ui/agent_client.py
"""Bridge between the Streamlit UI and the sandboxed OpenCode agent.

Delivers vulnerability scanning prompts via `openshell sandbox exec -- opencode run`,
so every agent invocation runs under the OpenShell policy proxy inside the Kata VM.
"""
import os
import re
import io
import json
import base64
import tarfile
import tempfile
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

BLOCKED_RE = re.compile(r"policy_denied|egress.*blocked|connection refused|host not allowed", re.IGNORECASE)
MAX_REPO_MB = 200


def stage_repo(git_url: str, client, sandbox_name: str, workspace: str, timeout: float) -> str:
    """Clone repo in the UI pod (full internet), tar+base64 it, extract into sandbox.

    Returns the sandbox path where the repo landed (/sandbox/tmp/scan).
    Raises on clone failure, size limit exceeded, or transfer error.
    """
    import git

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"   # never prompt for credentials
            env["GIT_ASKPASS"] = "echo"         # return empty string for any auth prompt
            git.Repo.clone_from(
                git_url, tmpdir,
                depth=1, single_branch=True,
                env=env,
            )
        except git.exc.GitCommandError as e:
            raise RuntimeError(f"Clone failed: {e}") from e

        # Check size
        total = sum(f.stat().st_size for f in __import__('pathlib').Path(tmpdir).rglob('*') if f.is_file())
        if total > MAX_REPO_MB * 1024 * 1024:
            raise RuntimeError(f"Repository too large ({total // (1024*1024)} MB, limit {MAX_REPO_MB} MB)")

        # Build compressed tar (exclude .git, max compression)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=9) as tar:
            tar.add(tmpdir, arcname='scan',
                    filter=lambda m: None if '/.git' in m.name else m)
        raw = buf.getvalue()

    # Transfer raw bytes using Python one-liners per chunk.
    # 4000 bytes → repr ≤ ~20 000 chars → safely under 32 KB gRPC arg limit.
    CHUNK = 4000
    client.exec(
        sandbox=sandbox_name,
        command=['sh', '-c', 'mkdir -p /sandbox/tmp && rm -f /sandbox/tmp/_repo.tar.gz'],
        workspace=workspace, timeout_seconds=10, no_login_shell=True,
    )
    for i in range(0, len(raw), CHUNK):
        chunk_bytes = raw[i:i + CHUNK]
        py = (
            "f=open('/sandbox/tmp/_repo.tar.gz','ab');"
            f"f.write(bytes({list(chunk_bytes)}));"
            "f.close()"
        )
        client.exec(
            sandbox=sandbox_name,
            command=['python3', '-c', py],
            workspace=workspace, timeout_seconds=15, no_login_shell=True,
        )
    # Extract
    client.exec(
        sandbox=sandbox_name,
        command=['sh', '-c',
                 'rm -rf /sandbox/tmp/scan && '
                 'tar xz -f /sandbox/tmp/_repo.tar.gz -C /sandbox/tmp && '
                 'rm /sandbox/tmp/_repo.tar.gz'],
        workspace=workspace, timeout_seconds=60, no_login_shell=True,
    )
    return '/sandbox/tmp/scan'

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


def stage_and_run(git_url: str, scan_id: str = "") -> "tuple[str, AgentResult]":
    """Clone repo in UI pod, stage to sandbox, return (sandbox_path, AgentResult).

    Returns the sandbox path and a stub AgentResult(text='staged') so the
    caller knows where the repo landed before running the real scan prompt.
    Used to bypass the broken DNS inside the Kata VM.
    """
    from openshell.sandbox import SandboxClient

    sandbox_name = os.environ.get("SANDBOX_NAME", "opencode-dual")
    gateway_endpoint = os.environ.get("OPENSHELL_GATEWAY_ENDPOINT", "http://openshell-kata:8080")
    timeout = float(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "1800"))
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")

    parsed = urlparse(gateway_endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    endpoint = f"{host}:{port}"

    client = SandboxClient(endpoint=endpoint, tls=None, bearer_token=None, timeout=timeout)
    try:
        path = stage_repo(git_url, client, sandbox_name, workspace, timeout)
    finally:
        client.close()
    return path


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
        result = client.exec(
            sandbox=sandbox_name,
            command=["opencode", "run", prompt],
            workspace=workspace,
            timeout_seconds=timeout,
            no_login_shell=True,
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
