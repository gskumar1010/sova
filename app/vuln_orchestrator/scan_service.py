"""Full scan pipeline: clone → stage to sandbox → semgrep → bandit → AI.

Runs as a background asyncio task. Updates _progress store in main.py
so the SSE stream can relay events to the Vue frontend in real time.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

GATEWAY = os.environ.get("OPENSHELL_GATEWAY_ENDPOINT", "http://openshell-kata:8080")
SANDBOX = os.environ.get("SANDBOX_NAME", "opencode-dual")
WORKSPACE = os.environ.get("OPENSHELL_WORKSPACE", "default")
TIMEOUT = float(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "1800"))
MAX_REPO_MB = 200
CHUNK = 20_000  # base64 chars per exec chunk — stays under 32KB gRPC limit


def _make_client():
    from openshell.sandbox import SandboxClient
    from urllib.parse import urlparse
    p = urlparse(GATEWAY)
    host = p.hostname or "127.0.0.1"
    port = p.port or 80
    return SandboxClient(endpoint=f"{host}:{port}", tls=None, bearer_token=None, timeout=TIMEOUT)


def _post_event(progress: dict, scan_id: str, step: str, status: str, detail: str = ""):
    """Append a step event to the shared progress store."""
    if scan_id not in progress:
        progress[scan_id] = []
    progress[scan_id].append({
        "step": step, "status": status, "detail": detail,
        "ts": time.strftime("%H:%M:%S"),
    })
    log.info("[%s] %s:%s %s", scan_id[:8], step, status, detail)


async def run_full_scan(
    git_url: str,
    scan_id: str,
    progress: dict,
    scan_manager,
) -> dict:
    """Execute the full scan pipeline. Runs in a thread pool via asyncio.to_thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _run_full_scan_sync, git_url, scan_id, progress, scan_manager
    )


def _run_full_scan_sync(git_url: str, scan_id: str, progress: dict, scan_manager) -> dict:
    try:
        client = _make_client()
    except Exception as e:
        _post_event(progress, scan_id, "clone", "failed", f"OpenShell unavailable: {e}")
        scan_manager.update_status(scan_id, "failed")
        return {"error": str(e)}

    try:
        # ── Step 1: Clone ──────────────────────────────────────────────────
        _post_event(progress, scan_id, "clone", "started", "Cloning repository…")
        sandbox_path = _stage_repo(git_url, client, scan_id)
        _post_event(progress, scan_id, "clone", "completed", "Staged to /sandbox/tmp/scan")

        # ── Step 2: Semgrep ───────────────────────────────────────────────
        _post_event(progress, scan_id, "semgrep", "started", "Fetching rulesets & scanning…")
        sarif_data = _run_semgrep(client, sandbox_path, scan_id)
        count = len(sarif_data.get("runs", [{}])[0].get("results", [])) if sarif_data else 0
        _post_event(progress, scan_id, "semgrep", "completed", f"{count} findings")

        # ── Step 3: Bandit ────────────────────────────────────────────────
        _post_event(progress, scan_id, "bandit", "started", "Analyzing Python AST…")
        bandit_count = _run_bandit(client, sandbox_path, scan_id)
        _post_event(progress, scan_id, "bandit", "completed", f"{bandit_count} findings")

        # ── Step 4: AI Analysis (via OpenCode) ────────────────────────────
        _post_event(progress, scan_id, "analysis", "started", f"Sending to nemotron-30b-vulkan…")
        agent_text = _run_ai(client, sandbox_path, sarif_data, count, scan_id)
        _post_event(progress, scan_id, "analysis", "completed", "Analysis complete")

        # ── Store results ──────────────────────────────────────────────────
        if sarif_data:
            scan_manager.store_sarif(scan_id, json.dumps(sarif_data))
        scan_manager.update_status(scan_id, "completed")

        return {
            "scan_id": scan_id,
            "sarif": sarif_data,
            "agent_text": agent_text,
            "finding_count": count,
        }

    except Exception as e:
        log.exception("Scan %s failed: %s", scan_id, e)
        _post_event(progress, scan_id, "clone", "failed", str(e))
        scan_manager.update_status(scan_id, "failed")
        return {"error": str(e)}
    finally:
        try:
            client.close()
        except Exception:
            pass


def _stage_repo(git_url: str, client, scan_id: str) -> str:
    """Clone locally, compress, transfer to sandbox. Returns sandbox path."""
    import git

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            git.Repo.clone_from(git_url, tmpdir, depth=1, single_branch=True, env=env)
        except git.exc.GitCommandError as e:
            raise RuntimeError(f"Clone failed: {e}") from e

        total = sum(f.stat().st_size for f in Path(tmpdir).rglob('*') if f.is_file())
        if total > MAX_REPO_MB * 1024 * 1024:
            raise RuntimeError(f"Repo too large ({total//1024//1024} MB, limit {MAX_REPO_MB} MB)")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=9) as tar:
            tar.add(tmpdir, arcname='scan',
                    filter=lambda m: None if '/.git' in m.name else m)
        raw = buf.getvalue()

    b64 = base64.b64encode(raw).decode('ascii')
    client.exec(sandbox=SANDBOX, command=['sh', '-c',
        'mkdir -p /sandbox/tmp && rm -f /sandbox/tmp/_repo.b64'],
        workspace=WORKSPACE, timeout_seconds=10, no_login_shell=True)

    for i in range(0, len(b64), CHUNK):
        chunk = b64[i:i + CHUNK]
        op = '>' if i == 0 else '>>'
        client.exec(sandbox=SANDBOX,
            command=['sh', '-c', f'printf "%s" "{chunk}" {op} /sandbox/tmp/_repo.b64'],
            workspace=WORKSPACE, timeout_seconds=30, no_login_shell=True)

    client.exec(sandbox=SANDBOX, command=['sh', '-c',
        'rm -rf /sandbox/tmp/scan && '
        'base64 -d /sandbox/tmp/_repo.b64 | tar xz -C /sandbox/tmp && '
        'rm /sandbox/tmp/_repo.b64'],
        workspace=WORKSPACE, timeout_seconds=60, no_login_shell=True)

    return '/sandbox/tmp/scan'


def _run_semgrep(client, sandbox_path: str, scan_id: str) -> dict | None:
    r = client.exec(sandbox=SANDBOX,
        command=['/sandbox/vuln_scan.py', 'semgrep',
                 '--path', sandbox_path, '--output', '/sandbox/tmp/semgrep.sarif'],
        workspace=WORKSPACE, timeout_seconds=600, no_login_shell=True)
    if r.exit_code != 0:
        log.warning("semgrep exit %s: %s", r.exit_code, r.stderr[:200])
        return None
    sarif_r = client.exec(sandbox=SANDBOX, command=['cat', '/sandbox/tmp/semgrep.sarif'],
        workspace=WORKSPACE, timeout_seconds=30, no_login_shell=True)
    try:
        return json.loads(sarif_r.stdout)
    except Exception:
        return None


def _run_bandit(client, sandbox_path: str, scan_id: str) -> int:
    r = client.exec(sandbox=SANDBOX,
        command=['/sandbox/vuln_scan.py', 'bandit',
                 '--path', sandbox_path, '--output', '/sandbox/tmp/bandit.json'],
        workspace=WORKSPACE, timeout_seconds=300, no_login_shell=True)
    if r.exit_code not in (0, 1):  # bandit exits 1 when findings exist
        return 0
    try:
        bj = client.exec(sandbox=SANDBOX,
            command=['sh', '-c', "python3 -c \"import json; d=json.load(open('/sandbox/tmp/bandit.json')); print(len(d.get('results',[])))\""],
            workspace=WORKSPACE, timeout_seconds=15, no_login_shell=True)
        return int(bj.stdout.strip() or "0")
    except Exception:
        return 0


def _run_ai(client, sandbox_path: str, sarif_data: dict, count: int, scan_id: str) -> str:
    prompt = (
        f"@security-analyst The repository at {sandbox_path} has been scanned. "
        f"Semgrep found {count} findings in /sandbox/tmp/semgrep.sarif. "
        f"Extract COUNTS ONLY: "
        f"jq '.runs[0].results | length' /sandbox/tmp/semgrep.sarif and "
        f"jq '[.runs[0].results[].level] | group_by(.) | map({{(.[0]):length}}) | add' /sandbox/tmp/semgrep.sarif. "
        f"Report ONLY: total count, severity breakdown, top 5 rule IDs."
    )
    r = client.exec(sandbox=SANDBOX, command=["opencode", "run", prompt],
        workspace=WORKSPACE, timeout_seconds=int(TIMEOUT), no_login_shell=True)
    stdout = r.stdout or ""
    from re import sub
    clean = sub(r"(?m)^\s*>\s*build\b.*$", "", stdout).strip()
    return clean or stdout[:2000]
