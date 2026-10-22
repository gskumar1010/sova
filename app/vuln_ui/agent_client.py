# app/vuln_ui/agent_client.py
"""Bridge between the Streamlit UI and the sandboxed OpenCode agent.

Delivers vulnerability scanning prompts via `openshell sandbox exec -- opencode run`,
so every agent invocation runs under the OpenShell policy proxy inside the Kata VM.
"""
import os
import re
import io
import json
import time
import base64
import tarfile
import tempfile
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

# Per-session trace log — written to /tmp/sova_trace_<scan_id>.log
_log = logging.getLogger("sova.agent")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)


def _trace_log(scan_id: str, msg: str) -> None:
    """Append a line to the per-session trace file and the Python logger."""
    _log.debug("[%s] %s", scan_id[:8], msg)
    try:
        with open(f"/tmp/sova_trace_{scan_id}.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def get_trace(scan_id: str) -> str:
    """Return the full trace log for a scan session."""
    try:
        with open(f"/tmp/sova_trace_{scan_id}.log") as f:
            return f.read()
    except FileNotFoundError:
        return "(no trace log yet)"

BLOCKED_RE = re.compile(r"policy_denied|egress.*blocked|connection refused|host not allowed", re.IGNORECASE)
MAX_REPO_MB = 200


def stage_repo(git_url: str, client, sandbox_name: str, workspace: str, timeout: float, scan_id: str = "") -> str:
    """Clone repo in the UI pod (full internet), tar+base64 it, extract into sandbox.

    Returns the sandbox path where the repo landed (/sandbox/tmp/scan).
    Raises on clone failure, size limit exceeded, or transfer error.
    """
    import git

    _trace_log(scan_id, f"stage_repo: cloning {git_url}")
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_ASKPASS"] = "echo"
            git.Repo.clone_from(git_url, tmpdir, depth=1, single_branch=True, env=env)
            _trace_log(scan_id, "Clone succeeded")
        except git.exc.GitCommandError as e:
            _trace_log(scan_id, f"Clone FAILED: {e}")
            raise RuntimeError(f"Clone failed: {e}") from e

        total = sum(f.stat().st_size for f in __import__('pathlib').Path(tmpdir).rglob('*') if f.is_file())
        _trace_log(scan_id, f"Repo size: {total//1024//1024} MB")
        if total > MAX_REPO_MB * 1024 * 1024:
            raise RuntimeError(f"Repository too large ({total//1024//1024} MB, limit {MAX_REPO_MB} MB)")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=9) as tar:
            tar.add(tmpdir, arcname='scan',
                    filter=lambda m: None if '/.git' in m.name else m)
        raw = buf.getvalue()
        _trace_log(scan_id, f"Compressed tar size: {len(raw)//1024} KB, {len(raw)//4000 + 1} chunks to send")

    # Base64 encode for reliable transfer (handles binary data correctly)
    b64 = base64.b64encode(raw).decode('ascii')
    # Use 20KB chunks to stay well under 32KB gRPC limit (base64 is ~1.33x larger)
    CHUNK = 20000
    n_chunks = len(b64) // CHUNK + 1
    _trace_log(scan_id, f"Sending {n_chunks} base64 chunks to sandbox...")
    t0 = time.time()
    client.exec(
        sandbox=sandbox_name,
        command=['sh', '-c', 'mkdir -p /sandbox/tmp && rm -f /sandbox/tmp/_repo.b64 /sandbox/code_graph_output.json /sandbox/*.sarif'],
        workspace=workspace, timeout_seconds=10, no_login_shell=True,
    )
    # Send chunks and append to base64 file
    for i in range(0, len(b64), CHUNK):
        chunk = b64[i:i + CHUNK]
        cmd = f'printf "%s" "{chunk}" >> /sandbox/tmp/_repo.b64' if i > 0 else f'printf "%s" "{chunk}" > /sandbox/tmp/_repo.b64'
        client.exec(
            sandbox=sandbox_name,
            command=['sh', '-c', cmd],
            workspace=workspace, timeout_seconds=15, no_login_shell=True
        )
    _trace_log(scan_id, f"Transfer done in {time.time()-t0:.1f}s — extracting...")
    r = client.exec(
        sandbox=sandbox_name,
        command=['sh', '-c',
                 'rm -rf /sandbox/tmp/scan && '
                 'base64 -d /sandbox/tmp/_repo.b64 | tar xz -C /sandbox/tmp && '
                 'rm /sandbox/tmp/_repo.b64 && '
                 'ls /sandbox/tmp/scan | head -5'],
        workspace=workspace, timeout_seconds=60, no_login_shell=True,
    )
    _trace_log(scan_id, f"Extract exit={r.exit_code} top-files: {r.stdout.strip()[:100]}")
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


def _make_client():
    """Build a SandboxClient from env."""
    from openshell.sandbox import SandboxClient
    gw = os.environ.get("OPENSHELL_GATEWAY_ENDPOINT", "http://openshell-kata:8080")
    parsed = urlparse(gw)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    timeout = float(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "1800"))
    return SandboxClient(endpoint=f"{host}:{port}", tls=None, bearer_token=None, timeout=timeout), timeout


@dataclass
class StepResult:
    step: str
    success: bool
    detail: str = ""
    sarif: Optional[Dict[str, Any]] = None


def run_scan_steps(sandbox_path: str, scan_id: str, on_step: callable = None) -> "tuple[list[StepResult], AgentResult]":
    """Run semgrep, bandit, and AI analysis as separate exec calls.

    `on_step(step, status, detail)` is called after each step completes so
    the UI can advance the pipeline in real time.

    Returns (step_results, AgentResult) where AgentResult carries the
    final text and sarif_data.
    """
    from openshell.sandbox import SandboxClient

    sandbox_name = os.environ.get("SANDBOX_NAME", "opencode-dual")
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    client, timeout = _make_client()
    step_results = []
    sarif_data = None

    def _exec(cmd, step_timeout=300):
        return client.exec(
            sandbox=sandbox_name,
            command=cmd,
            workspace=workspace,
            timeout_seconds=step_timeout,
            no_login_shell=True,
        )

    def _notify(step, status, detail=""):
        _trace_log(scan_id, f"step {step}: {status} {detail}")
        if on_step:
            on_step(step, status, detail)

    try:
        # Locate vuln_scan.py — startup.sh copies to /sandbox/ but may race
        vs_check = _exec(["sh", "-c",
            "test -f /sandbox/vuln_scan.py && echo /sandbox/vuln_scan.py "
            "|| echo /home/user/workspace/vuln_scan.py"],
            step_timeout=10)
        vs_path = vs_check.stdout.strip() or "/sandbox/vuln_scan.py"
        _trace_log(scan_id, f"vuln_scan.py path: {vs_path}")

        # ── Step 1: Semgrep ───────────────────────────────────────────────
        _notify("semgrep", "started")
        t0 = time.time()
        r = _exec([
            vs_path, "semgrep",
            "--path", sandbox_path,
            "--output", "/sandbox/tmp/semgrep.sarif",
        ], step_timeout=600)
        elapsed = time.time() - t0
        _trace_log(scan_id, f"semgrep exit={r.exit_code} elapsed={elapsed:.0f}s stderr={r.stderr[:200]}")
        if r.exit_code == 0:
            sarif_r = _exec(["cat", "/sandbox/tmp/semgrep.sarif"], step_timeout=30)
            try:
                sarif_data = json.loads(sarif_r.stdout)
                count = len(sarif_data.get("runs", [{}])[0].get("results", []))
                detail = f"{count} findings · {elapsed:.0f}s"
            except Exception:
                detail = f"{elapsed:.0f}s"
            _notify("semgrep", "completed", detail)
            step_results.append(StepResult("semgrep", True, detail, sarif_data))
        else:
            _notify("semgrep", "failed", r.stderr[:100])
            step_results.append(StepResult("semgrep", False, r.stderr[:80]))

        # ── Step 2: Bandit ────────────────────────────────────────────────
        _notify("bandit", "started")
        t0 = time.time()
        r = _exec([
            vs_path, "bandit",
            "--path", sandbox_path,
            "--output", "/sandbox/tmp/bandit.json",
        ], step_timeout=300)
        elapsed = time.time() - t0
        _trace_log(scan_id, f"bandit exit={r.exit_code} elapsed={elapsed:.0f}s")
        if r.exit_code == 0:
            try:
                bj = _exec(["sh", "-c", "python3 -c \"import json,sys; d=json.load(open('/sandbox/tmp/bandit.json')); print(len(d.get('results',d.get('results',[]))))\" 2>/dev/null || echo 0"], step_timeout=15)
                count = int(bj.stdout.strip() or "0")
                detail = f"{count} findings · {elapsed:.0f}s"
            except Exception:
                detail = f"{elapsed:.0f}s"
            _notify("bandit", "completed", detail)
            step_results.append(StepResult("bandit", True, detail))
        else:
            _notify("bandit", "failed", r.stderr[:80])
            step_results.append(StepResult("bandit", False, r.stderr[:80]))

        # ── Step 3: AI Analysis ───────────────────────────────────────────
        _notify("analysis", "started")
        semgrep_count = next((s.sarif and len(s.sarif.get("runs",[{}])[0].get("results",[])) for s in step_results if s.step=="semgrep" and s.sarif), 0)
        ai_prompt = (
            f"@security-analyst The repository at {sandbox_path} has been scanned. "
            f"Semgrep found {semgrep_count} findings in /sandbox/tmp/semgrep.sarif. "
            f"Bandit results are in /sandbox/tmp/bandit.json. "
            f"Extract COUNTS ONLY — do NOT read full file contents: "
            f"jq '.runs[0].results | length' /sandbox/tmp/semgrep.sarif and "
            f"jq '[.runs[0].results[].level] | group_by(.) | map({{(.[0]):length}}) | add' /sandbox/tmp/semgrep.sarif. "
            f"Report ONLY: total count, severity breakdown, top 5 rule IDs."
        )
        t0 = time.time()
        ai_r = _exec(["opencode", "run", ai_prompt], step_timeout=int(timeout))
        elapsed = time.time() - t0
        _trace_log(scan_id, f"AI exit={ai_r.exit_code} elapsed={elapsed:.0f}s stdout={len(ai_r.stdout or '')} stderr={len(ai_r.stderr or '')}")
        _notify("analysis", "completed" if ai_r.exit_code == 0 else "failed", f"{elapsed:.0f}s")

        stdout = ai_r.stdout or ""
        stderr = ai_r.stderr or ""
        raw = stdout + stderr
        blocked = bool(BLOCKED_RE.search(raw))
        text = _clean(stdout) if stdout.strip() else _clean(raw)
        if not text.strip() and raw.strip():
            text = raw[:2000]

        return step_results, AgentResult(text=text, egress_blocked=blocked, raw=raw, sarif_data=sarif_data)

    finally:
        client.close()


def stage_and_run(git_url: str, scan_id: str = "") -> str:
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

    _trace_log(scan_id, f"stage_and_run: git_url={git_url} sandbox={sandbox_name} gateway={endpoint} timeout={timeout}")
    client = SandboxClient(endpoint=endpoint, tls=None, bearer_token=None, timeout=timeout)
    try:
        _trace_log(scan_id, "Cloning repo in UI pod...")
        t0 = time.time()
        path = stage_repo(git_url, client, sandbox_name, workspace, timeout, scan_id=scan_id)
        _trace_log(scan_id, f"Staged to {path} in {time.time()-t0:.1f}s")
    finally:
        client.close()
    return path


def run_agent(prompt: str, scan_id: str = "", _sid: str = "") -> AgentResult:
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

    sid = _sid or scan_id
    logger.info(f"run_agent: sandbox={sandbox_name}, timeout={timeout}s, prompt_len={len(prompt)}")
    _trace_log(sid, f"run_agent: sandbox={sandbox_name} timeout={timeout}s gateway={gateway_endpoint}")

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
        _trace_log(sid, f"exec: opencode run (prompt_len={len(prompt)})")
        t0 = time.time()
        result = client.exec(
            sandbox=sandbox_name,
            command=["opencode", "run", prompt],
            workspace=workspace,
            timeout_seconds=timeout,
            no_login_shell=True,
        )
        elapsed = time.time() - t0

        stdout = result.stdout if result.stdout else ""
        stderr = result.stderr if result.stderr else ""
        raw = stdout + stderr

        logger.info(f"Agent completed: exit_code={result.exit_code}, stdout_len={len(stdout)}, stderr_len={len(stderr)}")
        _trace_log(sid, f"exec done: exit={result.exit_code} elapsed={elapsed:.1f}s stdout_len={len(stdout)} stderr_len={len(stderr)}")
        if stderr.strip():
            _trace_log(sid, f"STDERR: {stderr[:500]}")
        if stdout.strip():
            _trace_log(sid, f"STDOUT[:500]: {stdout[:500]}")

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

        # Read SARIF directly from sandbox — more reliable than parsing agent stdout
        sarif_data = None
        try:
            sarif_result = client.exec(
                sandbox=sandbox_name,
                command=["cat", "/sandbox/tmp/semgrep.sarif"],
                workspace=workspace,
                timeout_seconds=30,
                no_login_shell=True,
            )
            if sarif_result.exit_code == 0 and sarif_result.stdout.strip():
                sarif_data = json.loads(sarif_result.stdout)
                _trace_log(sid, f"SARIF read directly: {len(sarif_data.get('runs',[{}])[0].get('results',[]))} findings")
            else:
                # Fallback: try regex on raw output
                json_match = re.search(r'\{[^{}]*"version"\s*:\s*"2\.1\.0"[^{}]*\}', raw, re.DOTALL)
                if json_match:
                    sarif_data = json.loads(json_match.group(0))
        except Exception as e:
            _trace_log(sid, f"SARIF read error: {e}")

        return AgentResult(text=text, egress_blocked=blocked, raw=raw, sarif_data=sarif_data)

    finally:
        client.close()
