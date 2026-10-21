"""Vulnerability Orchestrator API: Manages vulnerability scans and tool execution."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
import uuid

from app.vuln_orchestrator.scan_manager import ScanManager
from app.vuln_orchestrator.scanners.semgrep_runner import run_semgrep
from app.vuln_orchestrator.scanners.bandit_runner import run_bandit
from app.vuln_orchestrator.scanners.safety_runner import run_safety

app = FastAPI(title="SOVA Vulnerability Orchestrator", version="1.0.0")
scan_manager = ScanManager()

# In-memory progress store: scan_id -> list of step events
_progress: dict = {}


class ScanRequest(BaseModel):
    git_url: str


class ToolRequest(BaseModel):
    path: str
    output: Optional[str] = None


class SafetyRequest(BaseModel):
    requirements_file: str


class SARIFSubmission(BaseModel):
    sarif_content: str


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "vuln-orchestrator"}


# ── Progress tracking ─────────────────────────────────────────────────────────

class ProgressEvent(BaseModel):
    step: str    # e.g. "clone", "semgrep", "bandit", "analysis"
    status: str  # "started" | "completed" | "failed"
    detail: Optional[str] = None


@app.post("/scan/progress/{scan_id}")
def post_progress(scan_id: str, event: ProgressEvent):
    """Agent calls this to report step completion inside the sandbox."""
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
    """UI polls this to get live step updates."""
    return {"scan_id": scan_id, "events": _progress.get(scan_id, [])}


@app.post("/scan/start")
def start_scan(request: ScanRequest):
    """Initiate a new vulnerability scan."""
    scan_id = str(uuid.uuid4())
    scan_manager.create_scan(scan_id, request.git_url)
    return {"scan_id": scan_id, "status": "initiated", "git_url": request.git_url}


@app.get("/scan/status/{scan_id}")
def get_scan_status(scan_id: str):
    """Get the current status of a scan."""
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
    """Retrieve SARIF results for a completed scan."""
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
    """Submit SARIF results for a scan."""
    scan = scan_manager.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    scan_manager.store_sarif(scan_id, submission.sarif_content)
    scan_manager.update_status(scan_id, "completed")
    return {"scan_id": scan_id, "status": "completed"}


@app.post("/tools/semgrep")
def run_semgrep_scan(request: ToolRequest):
    """Execute Semgrep scanner on the specified path."""
    try:
        result = run_semgrep(request.path, request.output)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Semgrep execution failed: {str(e)}")


@app.post("/tools/bandit")
def run_bandit_scan(request: ToolRequest):
    """Execute Bandit scanner on the specified path."""
    try:
        result = run_bandit(request.path, request.output)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bandit execution failed: {str(e)}")


@app.post("/tools/safety")
def run_safety_scan(request: SafetyRequest):
    """Execute Safety dependency scanner."""
    try:
        result = run_safety(request.requirements_file)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Safety execution failed: {str(e)}")
