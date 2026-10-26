"""Vulnerability Orchestrator API: Manages vulnerability scans and tool execution."""
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import json
import asyncio
import tempfile
import os
import git

from app.vuln_orchestrator.scan_manager import ScanManager
from app.vuln_orchestrator.scanners.semgrep_runner import run_semgrep
from app.vuln_orchestrator.scanners.bandit_runner import run_bandit
from app.vuln_orchestrator.scanners.safety_runner import run_safety

app = FastAPI(title="SOVA Vulnerability Orchestrator", version="2.0.0")
scan_manager = ScanManager()

# In-memory progress store: scan_id -> list of step events
_progress: dict = {}
# In-memory scan state for Vue frontend
_scan_state: dict = {}  # scan_id -> {status, sarif, summary, error}


# ── Models ────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    git_url: str

class FullScanRequest(BaseModel):
    git_url: str

class ToolRequest(BaseModel):
    path: str
    output: Optional[str] = None

class SafetyRequest(BaseModel):
    requirements_file: str

class SARIFSubmission(BaseModel):
    sarif_content: str

class ProgressEvent(BaseModel):
    step: str
    status: str
    detail: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    scan_id: Optional[str] = None


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "vuln-orchestrator"}


# ── Progress tracking ─────────────────────────────────────────────────────────

@app.post("/scan/progress/{scan_id}")
def post_progress(scan_id: str, event: ProgressEvent):
    if scan_id not in _progress:
        _progress[scan_id] = []
    _progress[scan_id].append({
        "step": event.step,
        "status": event.status,
        "detail": event.detail,
        "ts": datetime.utcnow().isoformat(),
    })
    return {"ok": True}


@app.get("/scan/progress/{scan_id}")
def get_progress(scan_id: str):
    return {"scan_id": scan_id, "events": _progress.get(scan_id, [])}


# ── Legacy scan endpoints (used by Streamlit) ─────────────────────────────────

@app.post("/scan/start")
def start_scan(request: ScanRequest):
    scan_id = str(uuid.uuid4())
    scan_manager.create_scan(scan_id, request.git_url)
    return {"scan_id": scan_id, "status": "initiated", "git_url": request.git_url}


@app.get("/scan/status/{scan_id}")
def get_scan_status(scan_id: str):
    scan = scan_manager.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {
        "scan_id": scan_id,
        "status": scan["status"],
        "git_url": scan["git_url"],
        "started_at": scan["started_at"],
        "completed_at": scan["completed_at"]
    }


@app.get("/scan/results/{scan_id}")
def get_scan_results(scan_id: str):
    scan = scan_manager.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Scan not completed (status: {scan['status']})")
    sarif_data = scan_manager.get_sarif(scan_id)
    if not sarif_data:
        raise HTTPException(status_code=404, detail="SARIF results not found")
    return sarif_data


@app.post("/scan/results/{scan_id}")
def submit_scan_results(scan_id: str, submission: SARIFSubmission):
    scan = scan_manager.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    scan_manager.store_sarif(scan_id, submission.sarif_content)
    scan_manager.update_status(scan_id, "completed")
    return {"scan_id": scan_id, "status": "completed"}


@app.post("/tools/semgrep")
def run_semgrep_scan(request: ToolRequest):
    try:
        result = run_semgrep(request.path, request.output)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Semgrep execution failed: {str(e)}")


@app.post("/tools/bandit")
def run_bandit_scan(request: ToolRequest):
    try:
        result = run_bandit(request.path, request.output)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bandit execution failed: {str(e)}")


@app.post("/tools/safety")
def run_safety_scan(request: SafetyRequest):
    try:
        result = run_safety(request.requirements_file)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Safety execution failed: {str(e)}")


# ── NEW: Vue Frontend API ─────────────────────────────────────────────────────

def _emit(scan_id: str, step: str, status: str, detail: str = None):
    """Add a progress event to the in-memory store."""
    if scan_id not in _progress:
        _progress[scan_id] = []
    _progress[scan_id].append({
        "step": step, "status": status,
        "detail": detail, "ts": datetime.utcnow().isoformat(),
    })


def _summarise_sarif(sarif: dict) -> dict:
    """Extract severity counts and top rules from SARIF."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    rule_freq: dict = {}
    findings = []

    for run in sarif.get("runs", []):
        tool_name = run.get("tool", {}).get("driver", {}).get("name", "unknown")
        rules_by_id = {
            r["id"]: r for r in run.get("tool", {}).get("driver", {}).get("rules", [])
        }
        for result in run.get("results", []):
            level = result.get("level", "note")
            rule_id = result.get("ruleId", "UNKNOWN")
            severity = {"error": "high", "warning": "medium", "note": "low"}.get(level, "low")
            rule_lower = rule_id.lower()
            msg_lower = result.get("message", {}).get("text", "").lower()
            # Elevate severity for dangerous patterns
            if any(s in rule_lower for s in ["injection", "sql", "rce", "exec", "shell", "command", "code-execution", "deserializ"]):
                severity = "critical"
            elif any(s in rule_lower for s in ["secret", "credential", "hardcoded", "password", "apikey", "api-key", "aws", "token", "private-key"]):
                severity = "critical"
            elif rule_id in ("B602", "B603", "B604", "B605", "B606", "B607") or \
                    any(s in rule_lower for s in ["subprocess", "shell-true", "shell_true", "b602", "b605", "b606"]):
                severity = "high"
            elif any(s in msg_lower for s in ["shell=true", "shell injection", "command injection", "arbitrary code"]):
                severity = "high"
            counts[severity] = counts.get(severity, 0) + 1
            rule_freq[rule_id] = rule_freq.get(rule_id, 0) + 1
            locs = result.get("locations", [])
            file_path = "unknown"
            line = 0
            snippet = ""
            if locs:
                pl = locs[0].get("physicalLocation", {})
                file_path = pl.get("artifactLocation", {}).get("uri", "unknown")
                region = pl.get("region", {})
                line = region.get("startLine", 0)
                snippet = region.get("snippet", {}).get("text", "")
            findings.append({
                "tool": tool_name,
                "rule_id": rule_id,
                "severity": severity,
                "message": result.get("message", {}).get("text", ""),
                "file": file_path,
                "line": line,
                "snippet": snippet,
            })

    top_rules = sorted(rule_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    total = sum(counts.values())
    risk = min(100, counts["critical"] * 10 + counts["high"] * 5 +
               counts["medium"] * 2 + counts["low"])
    return {
        "total": total,
        "risk": risk,
        "severity_counts": counts,
        "top_rules": [{"rule_id": r, "count": c} for r, c in top_rules],
        "findings": findings,
    }


def _run_full_scan(scan_id: str, git_url: str):
    """Background task: clone → semgrep → bandit → store results."""
    import tempfile, json
    _scan_state[scan_id] = {"status": "running", "sarif": None, "summary": None}
    scan_manager.create_scan(scan_id, git_url)

    tmpdir = tempfile.mkdtemp()
    try:
        # ── Clone ──────────────────────────────────────────────────────────
        _emit(scan_id, "clone", "started", "Cloning repository…")
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = "echo"
        repo = git.Repo.clone_from(git_url, tmpdir, depth=1, single_branch=True, env=env)
        commit = repo.head.commit.hexsha[:8]
        size_mb = round(sum(
            f.stat().st_size for f in __import__('pathlib').Path(tmpdir).rglob('*') if f.is_file()
        ) / 1024 / 1024, 1)
        _emit(scan_id, "clone", "completed", f"{size_mb} MB · {commit}")

        # ── Semgrep ────────────────────────────────────────────────────────
        _emit(scan_id, "semgrep", "started", "Fetching rulesets from semgrep.dev…")
        sg_out = os.path.join(tmpdir, "semgrep.sarif")
        sg_result = run_semgrep(tmpdir, sg_out)
        sg_sarif = sg_result.get("sarif", {}) if "sarif" in sg_result else {}
        sg_count = len(sg_sarif.get("runs", [{}])[0].get("results", [])) if sg_sarif else 0
        _emit(scan_id, "semgrep", "completed", f"{sg_count} findings")

        # ── Bandit ─────────────────────────────────────────────────────────
        _emit(scan_id, "bandit", "started", "Analyzing Python AST…")
        bn_out = os.path.join(tmpdir, "bandit.json")
        bn_result = run_bandit(tmpdir, bn_out)
        bn_count = len(bn_result.get("results", {}).get("results", [])) if "results" in bn_result else 0
        _emit(scan_id, "bandit", "completed", f"{bn_count} findings")

        # ── Merge SARIF ────────────────────────────────────────────────────
        merged = {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": []}
        if sg_sarif and sg_sarif.get("runs"):
            merged["runs"].extend(sg_sarif["runs"])

        # Convert bandit JSON to a minimal SARIF run
        if "results" in bn_result:
            bn_data = bn_result.get("results", {})
            bn_results_list = bn_data.get("results", [])
            bn_run = {
                "tool": {"driver": {"name": "Bandit", "rules": []}},
                "results": []
            }
            for issue in bn_results_list:
                sev = issue.get("issue_severity", "MEDIUM").lower()
                level = {"high": "error", "medium": "warning", "low": "note"}.get(sev, "note")
                bn_run["results"].append({
                    "ruleId": issue.get("test_id", "BXX"),
                    "level": level,
                    "message": {"text": issue.get("issue_text", "")},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": issue.get("filename", "")},
                            "region": {"startLine": issue.get("line_number", 0)}
                        }
                    }]
                })
            merged["runs"].append(bn_run)

        sarif_str = json.dumps(merged)
        scan_manager.store_sarif(scan_id, sarif_str)
        scan_manager.update_status(scan_id, "completed")

        # Summarise FIRST — used in AI prompt and final state
        summary = _summarise_sarif(merged)

        # ── AI Analysis (direct MaaS call) ────────────────────────────────
        agent_text = ""
        maas_url = os.environ.get("OPENAI_BASE_URL", "")
        maas_key = os.environ.get("OPENAI_API_KEY", "")
        if maas_url and maas_key and summary.get("total", 0) > 0:
            _emit(scan_id, "analysis", "started", "Sending findings to nemotron-30b-vulkan…")
            try:
                import requests as _req
                top_rules = ", ".join(
                    f"{r['ruleId']}({r['count']})" for r in summary.get("top_rules", [])[:5]
                )
                ai_prompt = (
                    f"Security scan of a code repository found {summary['total']} vulnerabilities: "
                    f"Critical: {summary['critical']}, High: {summary['high']}, "
                    f"Medium: {summary['medium']}, Low: {summary['low']}. "
                    f"Top rules triggered: {top_rules}. "
                    f"Provide a 3-sentence executive summary of the security posture and top remediation priorities."
                )
                resp = _req.post(
                    f"{maas_url.rstrip('/')}/chat/completions",
                    json={"model": os.environ.get("MODEL_NAME", "nemotron-30b-vulkan"),
                          "messages": [{"role": "user", "content": ai_prompt}],
                          "max_tokens": 256},
                    headers={"Authorization": f"Bearer {maas_key}",
                             "Content-Type": "application/json"},
                    timeout=120,
                )
                if resp.status_code == 200:
                    agent_text = resp.json()["choices"][0]["message"]["content"]
                    _emit(scan_id, "analysis", "completed", "AI summary generated")
                else:
                    _emit(scan_id, "analysis", "completed", f"AI unavailable ({resp.status_code})")
            except Exception as ai_err:
                _emit(scan_id, "analysis", "completed", f"AI skipped: {ai_err}")
        else:
            _emit(scan_id, "analysis", "completed", f"{summary['total']} total findings")

        _scan_state[scan_id] = {
            "status": "completed", "sarif": merged, "summary": summary,
            "agent_text": agent_text,
        }

    except Exception as exc:
        _emit(scan_id, "clone", "failed", str(exc)[:200])
        _scan_state[scan_id] = {"status": "failed", "error": str(exc), "sarif": None, "summary": None}
        scan_manager.update_status(scan_id, "failed")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/scan/full")
def api_start_full_scan(request: FullScanRequest, background_tasks: BackgroundTasks):
    """Start a full scan pipeline (clone → semgrep → bandit). Non-blocking."""
    scan_id = str(uuid.uuid4())
    _progress[scan_id] = []
    background_tasks.add_task(_run_full_scan, scan_id, request.git_url)
    return {"scan_id": scan_id, "status": "started"}


@app.get("/api/scan/stream/{scan_id}")
async def api_stream_progress(scan_id: str):
    """SSE stream of progress events for a scan."""
    async def event_generator():
        sent = 0
        while True:
            events = _progress.get(scan_id, [])
            for ev in events[sent:]:
                yield f"data: {json.dumps(ev)}\n\n"
                sent += 1
            state = _scan_state.get(scan_id, {})
            if state.get("status") in ("completed", "failed"):
                yield f"data: {json.dumps({'step':'done','status':state['status']})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/scan/full-result/{scan_id}")
def api_full_result(scan_id: str):
    """Return completed scan result with SARIF + summary."""
    state = _scan_state.get(scan_id)
    if not state:
        raise HTTPException(status_code=404, detail="Scan not found")
    if state["status"] == "running":
        raise HTTPException(status_code=202, detail="Scan still running")
    if state["status"] == "failed":
        raise HTTPException(status_code=500, detail=state.get("error", "Scan failed"))
    return {
        "scan_id": scan_id,
        "status": state["status"],
        "sarif": state["sarif"],
        "summary": state["summary"],
        "agent_text": state.get("agent_text", ""),
    }


@app.post("/api/chat")
def api_chat(request: ChatRequest):
    """Run message through OpenCode agent in the Kata VM sandbox."""
    from app.vuln_orchestrator.scan_service import _make_client, SANDBOX, WORKSPACE, TIMEOUT
    import re

    try:
        client = _make_client()
    except Exception as e:
        return {"role": "assistant", "text": f"Agent unavailable: {e}"}

    try:
        # Build context-aware prompt if a scan_id is provided
        prompt = request.message
        if request.scan_id and request.scan_id in _scan_state:
            state = _scan_state[request.scan_id]
            summary = state.get("summary") or {}
            if summary:
                top_rules = ", ".join(
                    f"{r['ruleId']}({r['count']})"
                    for r in summary.get("top_rules", [])[:5]
                )
                context = (
                    f"[Scan context: {summary.get('total', 0)} total findings — "
                    f"Critical:{summary.get('critical',0)} High:{summary.get('high',0)} "
                    f"Med:{summary.get('medium',0)} Low:{summary.get('low',0)}. "
                    f"Top rules: {top_rules}. "
                    f"Results are at /sandbox/tmp/semgrep.sarif and /sandbox/tmp/bandit.json]\n\n"
                )
                prompt = context + request.message

        r = client.exec(
            sandbox=SANDBOX,
            command=["opencode", "run", prompt],
            workspace=WORKSPACE,
            timeout_seconds=int(TIMEOUT),
            no_login_shell=True,
        )
        raw = (r.stdout or "") + (r.stderr or "")
        # Strip opencode build header and harmony tokens
        clean = re.sub(r"(?m)^\s*>\s*build\b.*$", "", r.stdout or "").strip()
        if "<channel|>" in clean:
            clean = clean.rsplit("<channel|>", 1)[-1]
        clean = re.sub(r"<\|?[^>\n]*\|?>", "", clean).strip()
        text = clean or raw[:2000] or "No response from agent."
        return {"role": "assistant", "text": text}
    except Exception as e:
        return {"role": "assistant", "text": f"Agent error: {e}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


# ── Upload endpoint: scan a local tar.gz/zip without needing a Git URL ────────

@app.post("/api/scan/upload")
async def api_upload_scan(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Accept a tar.gz or zip archive, extract and scan it."""
    import io, tarfile, zipfile, shutil
    scan_id = str(uuid.uuid4())
    _progress[scan_id] = []
    _scan_state[scan_id] = {"status": "running", "sarif": None, "summary": None}
    scan_manager.create_scan(scan_id, f"upload:{file.filename}")

    # Read uploaded file into memory
    data = await file.read()

    def run_uploaded_scan():
        tmpdir = tempfile.mkdtemp()
        try:
            _emit(scan_id, "clone", "started", f"Extracting {file.filename}…")
            buf = io.BytesIO(data)
            if file.filename.endswith(".zip"):
                with zipfile.ZipFile(buf) as z:
                    z.extractall(tmpdir)
            else:  # tar.gz / tgz
                with tarfile.open(fileobj=buf) as t:
                    t.extractall(tmpdir)
            _emit(scan_id, "clone", "completed", f"{len(data)//1024} KB extracted")

            _emit(scan_id, "semgrep", "started")
            sg_out = os.path.join(tmpdir, "semgrep.sarif")
            sg_result = run_semgrep(tmpdir, sg_out)
            sg_sarif = sg_result.get("sarif", {}) if "sarif" in sg_result else {}
            sg_count = len(sg_sarif.get("runs", [{}])[0].get("results", [])) if sg_sarif else 0
            _emit(scan_id, "semgrep", "completed", f"{sg_count} findings")

            _emit(scan_id, "bandit", "started")
            bn_out = os.path.join(tmpdir, "bandit.json")
            bn_result = run_bandit(tmpdir, bn_out)
            bn_count = len(bn_result.get("results", {}).get("results", [])) if "results" in bn_result else 0
            _emit(scan_id, "bandit", "completed", f"{bn_count} findings")

            merged = {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": []}
            if sg_sarif and sg_sarif.get("runs"):
                merged["runs"].extend(sg_sarif["runs"])
            if "results" in bn_result:
                bn_run = {"tool": {"driver": {"name": "Bandit", "rules": []}}, "results": []}
                for issue in bn_result.get("results", {}).get("results", []):
                    sev = issue.get("issue_severity", "MEDIUM").lower()
                    bn_run["results"].append({
                        "ruleId": issue.get("test_id", "BXX"),
                        "level": {"high": "error", "medium": "warning", "low": "note"}.get(sev, "note"),
                        "message": {"text": issue.get("issue_text", "")},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": issue.get("filename", "")}, "region": {"startLine": issue.get("line_number", 0)}}}]
                    })
                merged["runs"].append(bn_run)

            summary = _summarise_sarif(merged)
            scan_manager.store_sarif(scan_id, json.dumps(merged))
            scan_manager.update_status(scan_id, "completed")
            _scan_state[scan_id] = {"status": "completed", "sarif": merged, "summary": summary}
            _emit(scan_id, "analysis", "completed", f"{summary['total']} total findings")
        except Exception as exc:
            _emit(scan_id, "clone", "failed", str(exc)[:200])
            _scan_state[scan_id] = {"status": "failed", "error": str(exc), "sarif": None, "summary": None}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    background_tasks.add_task(run_uploaded_scan)
    return {"scan_id": scan_id, "status": "started", "filename": file.filename}


# ── Static files for Vue frontend ────────────────────────────────────────────

_DIST = os.path.join(os.path.dirname(__file__), "..", "vuln_ui_vue", "dist")
_DIST = os.path.normpath(_DIST)

if os.path.isdir(_DIST):
    # Serve ALL static files from dist (assets/, logo, favicon, etc.)
    # html=False so index.html is NOT auto-served — our SPA route below handles that
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    # Explicit routes for known root-level public files
    @app.get("/sova_logo.png", include_in_schema=False)
    async def serve_logo():
        return FileResponse(os.path.join(_DIST, "sova_logo.png"), media_type="image/png")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        p = os.path.join(_DIST, "favicon.ico")
        if os.path.isfile(p):
            return FileResponse(p, media_type="image/x-icon")
        raise HTTPException(status_code=404)

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str = ""):
        index = os.path.join(_DIST, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Vue build not found. Run `npm run build` in app/vuln_ui_vue/")
