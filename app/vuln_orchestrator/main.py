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

# ── Pre-cache: repos cloned at startup for instant scanning ───────────────────
CACHE_DIR = "/tmp/sova_repo_cache"
PREFETCH_REPOS = [
    ("devastator",     "https://github.com/pkredhat/devastator.git"),
    ("pygoat",         "https://github.com/adeyosemanputra/pygoat.git"),
    ("dvwa",           "https://github.com/digininja/DVWA.git"),
    ("terragoat",      "https://github.com/bridgecrewio/terragoat.git"),
    ("juice-shop",     "https://github.com/juice-shop/juice-shop.git"),
    ("webgoat-legacy", "https://github.com/WebGoat/WebGoat-Legacy.git"),
]

def _prefetch_repos():
    """Clone repos into cache dir in a background thread at startup."""
    import threading, git as _git, shutil
    os.makedirs(CACHE_DIR, exist_ok=True)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"

    def _clone(name, url):
        dest = os.path.join(CACHE_DIR, name)
        if os.path.isdir(dest):
            return  # already cached
        try:
            _git.Repo.clone_from(url, dest, depth=1, single_branch=True, env=env)
        except Exception:
            try: shutil.rmtree(dest, ignore_errors=True)
            except: pass

    threads = [threading.Thread(target=_clone, args=(n, u), daemon=True)
               for n, u in PREFETCH_REPOS]
    for t in threads: t.start()


@app.on_event("startup")
async def startup_event():
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _prefetch_repos)


def _cached_path(git_url: str) -> str | None:
    """Return cached clone path if this URL is pre-fetched, else None."""
    for name, url in PREFETCH_REPOS:
        if url == git_url or url.rstrip(".git") == git_url.rstrip(".git"):
            dest = os.path.join(CACHE_DIR, name)
            if os.path.isdir(dest):
                return dest
    return None


# In-memory progress store: scan_id -> list of step events
_progress: dict = {}
# In-memory scan state for Vue frontend
_scan_state: dict = {}  # scan_id -> {status, sarif, summary, error}
# Per-scan trace log: scan_id -> list of timestamped strings
_trace: dict = {}


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
    """Add a progress event and trace log entry."""
    if scan_id not in _progress:
        _progress[scan_id] = []
    _progress[scan_id].append({
        "step": step, "status": status,
        "detail": detail, "ts": datetime.utcnow().isoformat(),
    })
    # Also write to trace log
    if scan_id not in _trace:
        _trace[scan_id] = []
    ts = datetime.utcnow().strftime("%H:%M:%S")
    icon = "✓" if status == "completed" else "✗" if status == "failed" else "→"
    msg = f"[{ts}] {icon} {step}: {status}"
    if detail:
        msg += f" — {detail}"
    _trace[scan_id].append(msg)


def _trace_append(scan_id: str, msg: str):
    """Append a raw message to the trace log."""
    if scan_id not in _trace:
        _trace[scan_id] = []
    ts = datetime.utcnow().strftime("%H:%M:%S")
    _trace[scan_id].append(f"[{ts}] {msg}")


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
            # Extract CWE if present (bandit puts it in properties, semgrep in tags)
            cwe_id = None
            cwe_url = None
            props = result.get("properties", {})
            if "issue_cwe" in props:
                _cid = props["issue_cwe"].get("id")
                cwe_id = str(_cid) if _cid else None
                cwe_url = props["issue_cwe"].get("link") or (f"https://cwe.mitre.org/data/definitions/{cwe_id}.html" if cwe_id else None)
            elif not cwe_id and rule_id in rules_by_id:
                # Try semgrep rule tags — format is "CWE-78" or "CWE-78: Description"
                for tag in rules_by_id[rule_id].get("properties", {}).get("tags", []):
                    if tag.startswith("CWE-"):
                        raw_num = tag.split("-")[1].split(":")[0].strip()
                        if raw_num.isdigit():
                            cwe_id = raw_num
                            cwe_url = f"https://cwe.mitre.org/data/definitions/{cwe_id}.html"
                            break
            # Fallback: bandit rule_id → CWE map
            if not cwe_id:
                _BANDIT_CWE = {
                    "B102":78,"B103":732,"B105":259,"B106":259,"B107":259,
                    "B108":377,"B201":605,"B301":502,"B302":502,"B303":327,
                    "B304":327,"B305":327,"B307":78,"B308":352,"B310":601,
                    "B311":338,"B312":601,"B313":611,"B314":611,"B315":611,
                    "B320":611,"B321":321,"B322":676,"B323":295,"B324":327,
                    "B325":338,"B401":326,"B404":78,"B501":295,"B502":326,
                    "B503":326,"B504":326,"B505":326,"B601":78,"B602":78,
                    "B603":78,"B604":78,"B605":78,"B606":78,"B607":78,
                    "B608":89,"B609":78,"B610":89,"B611":89,"B701":94,
                    "B702":94,"B703":94,
                }
                cwe_num = _BANDIT_CWE.get(rule_id)
                if cwe_num:
                    cwe_id = str(cwe_num)
                    cwe_url = f"https://cwe.mitre.org/data/definitions/{cwe_num}.html"

            findings.append({
                "tool": tool_name,
                "rule_id": rule_id,
                "severity": severity,
                "message": result.get("message", {}).get("text", ""),
                "file": file_path,
                "line": line,
                "snippet": snippet,
                "cwe_id": cwe_id,
                "cwe_url": cwe_url,
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
    _trace_append(scan_id, f"Scan started: {git_url}")

    tmpdir = tempfile.mkdtemp()
    _use_cache = False
    try:
        # ── Clone (or use pre-fetched cache) ──────────────────────────────
        cached = _cached_path(git_url)
        if cached:
            _emit(scan_id, "clone", "started", "Using pre-cached clone…")
            scan_dir = cached
            _emit(scan_id, "clone", "completed", "Loaded from cache ⚡")
            _trace_append(scan_id, f"Cache hit: {cached}")
            _use_cache = True
        else:
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
            scan_dir = tmpdir

        # ── Semgrep ────────────────────────────────────────────────────────
        _emit(scan_id, "semgrep", "started", "Fetching rulesets from semgrep.dev…")
        sg_out = os.path.join(tmpdir, "semgrep.sarif")
        sg_result = run_semgrep(scan_dir, sg_out)
        sg_sarif = sg_result.get("sarif", {}) if "sarif" in sg_result else {}
        sg_count = len(sg_sarif.get("runs", [{}])[0].get("results", [])) if sg_sarif else 0
        _emit(scan_id, "semgrep", "completed", f"{sg_count} findings")

        # ── Bandit ─────────────────────────────────────────────────────────
        _emit(scan_id, "bandit", "started", "Analyzing Python AST…")
        bn_out = os.path.join(tmpdir, "bandit.json")
        bn_result = run_bandit(scan_dir, bn_out)
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
                    f"{r['rule_id']}({r['count']})" for r in summary.get("top_rules", [])[:5]
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

        # Kick off AI remediation in the background
        import threading as _threading
        _threading.Thread(target=_generate_remediation, args=(scan_id,), daemon=True).start()

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


@app.get("/api/scan/report/{scan_id}", response_class=None)
def api_scan_report(scan_id: str):
    """Generate a styled HTML security report (printable to PDF)."""
    from fastapi.responses import HTMLResponse
    from datetime import datetime as _dt

    state = _scan_state.get(scan_id)
    if not state or state["status"] != "completed":
        raise HTTPException(status_code=404, detail="Scan not found or not complete")

    s = state.get("summary") or {}
    findings = s.get("findings", [])
    git_url = scan_manager.get_scan(scan_id).get("git_url", "unknown") if scan_manager.get_scan(scan_id) else "unknown"

    sev_color = {"critical": "#ef4444", "high": "#f97316", "medium": "#eab308", "low": "#3b82f6"}
    risk = s.get("risk", 0)
    risk_color = "#ef4444" if risk >= 75 else "#f97316" if risk >= 45 else "#eab308" if risk >= 20 else "#22c55e"
    risk_label = "CRITICAL" if risk >= 75 else "HIGH" if risk >= 45 else "MEDIUM" if risk >= 20 else "LOW"

    findings_html = ""
    for i, f in enumerate(findings[:50], 1):
        sev = f.get("severity", "low")
        cwe = f'<a href="{f["cwe_url"]}" style="color:#3b82f6;font-size:0.75rem;">CWE-{f["cwe_id"]} ↗</a>' if f.get("cwe_id") else ""
        snippet = f"<pre style='background:#0d1117;padding:0.5rem;border-radius:4px;font-size:0.72rem;overflow-x:auto;margin-top:0.5rem;color:#94a3b8'>{f.get('snippet','')[:400]}</pre>" if f.get("snippet") else ""
        findings_html += f"""
        <tr>
          <td style="padding:0.5rem;border-bottom:1px solid #1e293b;">
            <span style="background:{sev_color.get(sev,'#64748b')}22;color:{sev_color.get(sev,'#64748b')};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;">{sev.upper()}</span>
          </td>
          <td style="padding:0.5rem;border-bottom:1px solid #1e293b;font-family:monospace;font-size:0.8rem;color:#94a3b8">{f.get('rule_id','')}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #1e293b;">{cwe}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #1e293b;font-size:0.8rem;color:#cbd5e1">{f.get('file','').split('/')[-1]}:{f.get('line','')}</td>
          <td style="padding:0.5rem;border-bottom:1px solid #1e293b;font-size:0.8rem;color:#94a3b8">{f.get('message','')[:120]}</td>
        </tr>"""

    agent_section = f"""
        <div style="margin-top:2rem;background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:1.5rem;">
          <h2 style="color:#00b4ff;margin:0 0 1rem;font-size:1rem;">AI Security Analysis</h2>
          <p style="color:#94a3b8;line-height:1.7;white-space:pre-wrap">{state.get('agent_text','')}</p>
        </div>""" if state.get("agent_text") else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SOVA Security Report — {git_url.split('/')[-1].replace('.git','')}</title>
<style>
  @media print {{ .no-print {{ display:none; }} body {{ background:#fff!important; color:#000!important; }} }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:#050810; color:#e2e8f0; font-family:Inter,-apple-system,sans-serif; padding:2rem; }}
  h1 {{ font-size:1.5rem; color:#f1f5f9; }}
  h2 {{ font-size:1rem; color:#00b4ff; margin:1.5rem 0 0.75rem; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; padding:0.5rem; background:#0d1117; color:#475569; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.06em; }}
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:2rem;padding-bottom:1.5rem;border-bottom:1px solid #1e293b;">
  <div>
    <div style="font-size:0.72rem;color:#475569;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.3rem;">SOVA — Sovereign Vulnerability Analysis Agent</div>
    <h1>Security Scan Report</h1>
    <div style="color:#475569;font-size:0.82rem;margin-top:0.4rem">{git_url}</div>
    <div style="color:#334155;font-size:0.75rem;margin-top:0.2rem">Generated: {_dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.1em;color:#475569">{risk_label} RISK</div>
    <div style="font-size:3rem;font-weight:800;color:{risk_color};line-height:1">{risk}</div>
    <div style="font-size:0.7rem;color:#475569">Risk Score</div>
  </div>
</div>

<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:1rem;margin-bottom:2rem;">
  {"".join(f'<div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:1rem;text-align:center"><div style="font-size:1.75rem;font-weight:700;color:{sev_color.get(k,"#fff")}">{v}</div><div style="font-size:0.7rem;color:#475569;text-transform:uppercase">{k}</div></div>' for k,v in [("total",s.get("total",0)),("critical",s.get("severity_counts",{}).get("critical",0)),("high",s.get("severity_counts",{}).get("high",0)),("medium",s.get("severity_counts",{}).get("medium",0)),("low",s.get("severity_counts",{}).get("low",0))])}
</div>

<h2>Top Rules</h2>
<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:2rem;">
  {"".join(f'<span style="background:#0d1117;border:1px solid #1e293b;border-radius:4px;padding:0.25rem 0.6rem;font-family:monospace;font-size:0.75rem;color:#94a3b8">{r["rule_id"]} ({r["count"]})</span>' for r in s.get("top_rules",[])[:5])}
</div>

<h2>Findings ({len(findings)} total, showing top 50)</h2>
<table>
  <thead><tr><th>Severity</th><th>Rule</th><th>CWE</th><th>Location</th><th>Description</th></tr></thead>
  <tbody>{findings_html}</tbody>
</table>

{agent_section}

<div style="margin-top:2rem;padding-top:1rem;border-top:1px solid #1e293b;font-size:0.72rem;color:#334155;">
  Scanned inside a Kata VM with OpenShell egress policy enforcement. Data never left the cluster.
  Red Hat OpenShift AI · DEMOJam 2027
</div>
</body>
</html>"""

    return HTMLResponse(content=html, headers={
        "Content-Disposition": f'attachment; filename="sova-report-{scan_id[:8]}.html"'
    })


# In-memory remediation store: scan_id -> {status, fixes: [...]}
_remediation: dict = {}


def _generate_remediation(scan_id: str):
    """Background: ask agent to fix top 3 critical/high findings."""
    from app.vuln_orchestrator.scan_service import _make_client, SANDBOX, WORKSPACE, TIMEOUT
    import re, threading

    state = _scan_state.get(scan_id, {})
    summary = state.get("summary") or {}
    findings = summary.get("findings", [])

    # Pick top 3 critical or high
    top = [f for f in findings if f.get("severity") in ("critical", "high")][:3]
    if not top:
        top = findings[:3]

    _remediation[scan_id] = {"status": "running", "fixes": []}

    try:
        client = _make_client()
    except Exception:
        _remediation[scan_id] = {"status": "done", "fixes": []}
        return

    fixes = []
    for f in top:
        rule_id = f.get("rule_id", "")
        file_path = f.get("file", "")
        line = f.get("line", 0)
        message = f.get("message", "")
        cwe_id = f.get("cwe_id", "")
        cwe_str = f" (CWE-{cwe_id})" if cwe_id else ""

        prompt = (
            f"Security finding in {file_path} at line {line}:\n"
            f"Rule: {rule_id}{cwe_str}\n"
            f"Issue: {message}\n\n"
            f"Read the file at /sandbox/tmp/scan/{'/'.join(file_path.split('/')[-2:])} "
            f"and show:\n"
            f"1. The vulnerable code (3-5 lines around line {line})\n"
            f"2. The fixed version\n"
            f"3. One sentence: why this fixes it\n\n"
            f"Format with ```python code blocks. Be concise."
        )

        try:
            r = client.exec(sandbox=SANDBOX, command=["opencode", "run", prompt],
                           workspace=WORKSPACE, timeout_seconds=int(TIMEOUT), no_login_shell=True)
            raw = r.stdout or r.stderr or ""
            clean = re.sub(r"(?m)^\s*>\s*build\b.*$", "", r.stdout or "").strip()
            if "<channel|>" in clean:
                clean = clean.rsplit("<channel|>", 1)[-1]
            clean = re.sub(r"<\|?[^>\n]*\|?>", "", clean).strip()
            text = clean or raw[:3000]
        except Exception as e:
            text = f"Could not generate fix: {e}"

        fixes.append({
            "rule_id": rule_id, "file": file_path, "line": line,
            "severity": f.get("severity"), "cwe_id": cwe_id,
            "message": message, "fix_text": text,
        })

    try: client.close()
    except Exception: pass

    _remediation[scan_id] = {"status": "done", "fixes": fixes}


@app.get("/api/scan/remediation/{scan_id}")
def api_remediation(scan_id: str):
    """Return AI remediation fixes for top findings."""
    return _remediation.get(scan_id, {"status": "not_started", "fixes": []})


# In-memory chat job store: job_id -> {status, text}
_chat_jobs: dict = {}


@app.post("/api/chat")
def api_chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """Submit a chat message as a background job — returns job_id immediately."""
    job_id = str(uuid.uuid4())
    _chat_jobs[job_id] = {"status": "running", "text": None}
    background_tasks.add_task(_run_chat_job, job_id, request.message, request.scan_id)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/chat/{job_id}")
def api_chat_result(job_id: str):
    """Poll for a chat job result."""
    job = _chat_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Chat job not found")
    return job


def _run_chat_job(job_id: str, message: str, scan_id: str | None):
    from app.vuln_orchestrator.scan_service import _make_client, SANDBOX, WORKSPACE, TIMEOUT
    import re

    try:
        client = _make_client()
    except Exception as e:
        _chat_jobs[job_id] = {"status": "done", "text": f"Agent unavailable: {e}"}
        return

    try:
        prompt = message
        if scan_id and scan_id in _scan_state:
            state = _scan_state[scan_id]
            summary = state.get("summary") or {}
            if summary:
                top_rules = ", ".join(
                    f"{r['rule_id']}({r['count']})"
                    for r in summary.get("top_rules", [])[:5]
                )
                context = (
                    f"[Scan context: {summary.get('total', 0)} total findings — "
                    f"Critical:{summary.get('critical',0)} High:{summary.get('high',0)} "
                    f"Med:{summary.get('medium',0)} Low:{summary.get('low',0)}. "
                    f"Top rules: {top_rules}. "
                    f"Results are at /sandbox/tmp/semgrep.sarif and /sandbox/tmp/bandit.json]\n\n"
                )
                prompt = context + message

        r = client.exec(
            sandbox=SANDBOX,
            command=["opencode", "run", prompt],
            workspace=WORKSPACE,
            timeout_seconds=int(TIMEOUT),
            no_login_shell=True,
        )
        raw = (r.stdout or "") + (r.stderr or "")
        clean = re.sub(r"(?m)^\s*>\s*build\b.*$", "", r.stdout or "").strip()
        if "<channel|>" in clean:
            clean = clean.rsplit("<channel|>", 1)[-1]
        clean = re.sub(r"<\|?[^>\n]*\|?>", "", clean).strip()
        text = clean or raw[:4000] or "No response from agent."
        _chat_jobs[job_id] = {"status": "done", "text": text}
    except Exception as e:
        _chat_jobs[job_id] = {"status": "done", "text": f"Agent error: {e}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


# ── Upload endpoint: scan a local tar.gz/zip without needing a Git URL ────────

@app.get("/api/scan/trace/{scan_id}")
def api_trace(scan_id: str):
    """Return the full trace log for a scan session."""
    return {"scan_id": scan_id, "lines": _trace.get(scan_id, [])}


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
