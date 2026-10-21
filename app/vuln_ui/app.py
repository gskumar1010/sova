"""SOVA Vulnerability Dashboard UI."""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json
import threading
import time
import uuid

import requests as _requests

from agent_client import run_agent, validate_git_url, parse_sarif

ORCHESTRATOR_URL = "http://vuln-orchestrator-api:8080"

# Bandit rule ID → CWE number (most common ones)
_BANDIT_CWE = {
    "B102": 78,  "B103": 732, "B104": 605, "B105": 259, "B106": 259,
    "B107": 259, "B108": 377, "B201": 605, "B301": 502, "B302": 502,
    "B303": 327, "B304": 327, "B305": 327, "B307": 78,  "B308": 352,
    "B310": 601, "B311": 338, "B312": 601, "B313": 611, "B314": 611,
    "B315": 611, "B316": 611, "B317": 611, "B318": 611, "B319": 611,
    "B320": 611, "B321": 321, "B322": 676, "B323": 295, "B324": 327,
    "B325": 338, "B401": 326, "B402": 326, "B403": 78,  "B404": 78,
    "B405": 611, "B406": 611, "B407": 611, "B408": 611, "B409": 611,
    "B410": 611, "B501": 295, "B502": 326, "B503": 326, "B504": 326,
    "B505": 326, "B506": 20,  "B507": 295, "B601": 78,  "B602": 78,
    "B603": 78,  "B604": 78,  "B605": 78,  "B606": 78,  "B607": 78,
    "B608": 89,  "B609": 78,  "B610": 89,  "B611": 89,  "B701": 94,
    "B702": 94,  "B703": 94,
}


def _cwe_url(rule_id: str) -> str | None:
    bid = rule_id.split(".")[-1].upper() if "." in rule_id else rule_id.upper()
    cwe = _BANDIT_CWE.get(bid)
    if cwe:
        return f"https://cwe.mitre.org/data/definitions/{cwe}.html", cwe
    return None, None


def _risk_score(sc: dict) -> int:
    raw = sc["critical"] * 10 + sc["high"] * 5 + sc["medium"] * 2 + sc["low"]
    return min(100, raw)


def _risk_color(score: int) -> str:
    if score >= 75: return "#ef4444"
    if score >= 45: return "#f97316"
    if score >= 20: return "#eab308"
    return "#22c55e"


def _poll_progress(scan_id: str) -> list:
    try:
        r = _requests.get(f"{ORCHESTRATOR_URL}/scan/progress/{scan_id}", timeout=3)
        return r.json().get("events", [])
    except Exception:
        return []

st.set_page_config(
    page_title="SOVA — Sovereign Vulnerability Analysis",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; }

[data-testid="stAppViewContainer"] {
  background: #050810;
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,180,255,0.08) 0%, transparent 60%),
    linear-gradient(rgba(0,180,255,0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,180,255,0.015) 1px, transparent 1px);
  background-size: 100% 100%, 40px 40px, 40px 40px;
}

[data-testid="stSidebar"] {
  background: rgba(8,12,24,0.95) !important;
  border-right: 1px solid rgba(0,180,255,0.12) !important;
  backdrop-filter: blur(20px);
}
[data-testid="stSidebar"] > div { padding-top: 1.5rem; }
[data-testid="stHeader"] { background: transparent !important; }
.block-container { padding: 1.5rem 2rem 3rem !important; max-width: 1400px; }

/* ── Global typography ── */
html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, sans-serif !important;
  color: #cbd5e1;
}
h1, h2, h3, h4, h5 { color: #f1f5f9 !important; }
code, pre { font-family: 'JetBrains Mono', monospace !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(0,180,255,0.3); border-radius: 2px; }

/* ═══════════════════════════════════════════
   HERO
═══════════════════════════════════════════ */
.hero-wrap {
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(0,180,255,0.06) 0%, rgba(8,12,24,0) 60%);
  border: 1px solid rgba(0,180,255,0.15);
  border-radius: 16px;
  padding: 2rem 2.5rem;
  margin-bottom: 1.75rem;
}
.hero-wrap::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 60% 80% at 0% 50%, rgba(0,180,255,0.07) 0%, transparent 70%);
  pointer-events: none;
}
.hero-grid-text {
  font-size: 0.68rem;
  font-family: 'JetBrains Mono', monospace;
  color: rgba(0,180,255,0.2);
  position: absolute;
  top: 1rem; right: 1.5rem;
  text-align: right;
  line-height: 1.6;
  letter-spacing: 0.05em;
}
.hero-eyebrow {
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #00b4ff;
  margin-bottom: 0.5rem;
}
.hero-title {
  font-size: 2.6rem;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -1px;
  margin: 0 0 0.4rem;
  background: linear-gradient(90deg, #f1f5f9 30%, #00b4ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-sub {
  font-size: 0.88rem;
  color: #64748b;
  margin-bottom: 1.1rem;
  max-width: 560px;
}
.pill-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.pill {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: rgba(0,180,255,0.06);
  border: 1px solid rgba(0,180,255,0.18);
  border-radius: 100px;
  padding: 0.3rem 0.9rem;
  font-size: 0.72rem;
  font-weight: 500;
  color: #94a3b8;
  letter-spacing: 0.02em;
}
.pill .dot {
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}
.dot-green { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
.dot-cyan  { background: #00b4ff; box-shadow: 0 0 6px #00b4ff; }
.dot-red   { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

/* ═══════════════════════════════════════════
   SCAN INPUT
═══════════════════════════════════════════ */
.scan-label {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #475569;
  margin-bottom: 0.5rem;
}
[data-testid="stTextInput"] > div > div > input {
  background: rgba(8,12,24,0.8) !important;
  border: 1px solid rgba(0,180,255,0.2) !important;
  border-radius: 10px !important;
  color: #f1f5f9 !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 0.9rem !important;
  padding: 0.7rem 1rem !important;
  transition: border-color 0.2s, box-shadow 0.2s;
}
[data-testid="stTextInput"] > div > div > input:focus {
  border-color: #00b4ff !important;
  box-shadow: 0 0 0 3px rgba(0,180,255,0.12), 0 0 20px rgba(0,180,255,0.08) !important;
  outline: none !important;
}
[data-testid="stTextInput"] > div > div > input::placeholder { color: #334155 !important; }

[data-testid="stButton"] > button {
  background: linear-gradient(135deg, #0084cc 0%, #0060aa 100%) !important;
  border: 1px solid rgba(0,180,255,0.3) !important;
  border-radius: 10px !important;
  color: #fff !important;
  font-weight: 600 !important;
  font-size: 0.88rem !important;
  letter-spacing: 0.03em !important;
  padding: 0.7rem 1.5rem !important;
  transition: all 0.2s !important;
  box-shadow: 0 0 20px rgba(0,132,204,0.25) !important;
}
[data-testid="stButton"] > button:hover {
  background: linear-gradient(135deg, #00a0e8 0%, #0080cc 100%) !important;
  box-shadow: 0 0 30px rgba(0,180,255,0.35) !important;
  transform: translateY(-1px) !important;
}

/* ═══════════════════════════════════════════
   METRIC CARDS
═══════════════════════════════════════════ */
.metrics-row { display: flex; gap: 0.75rem; margin: 1.5rem 0; }
.mcard {
  flex: 1;
  background: rgba(8,12,24,0.7);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 1.25rem 1rem;
  text-align: center;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(10px);
  transition: transform 0.2s, border-color 0.2s;
}
.mcard:hover { transform: translateY(-2px); }
.mcard::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 12px;
  pointer-events: none;
}
.mcard-total  { border-color: rgba(0,180,255,0.2); }
.mcard-total::after  { background: radial-gradient(ellipse at top, rgba(0,180,255,0.06) 0%, transparent 70%); }
.mcard-crit   { border-color: rgba(239,68,68,0.25); }
.mcard-crit::after   { background: radial-gradient(ellipse at top, rgba(239,68,68,0.07) 0%, transparent 70%); }
.mcard-high   { border-color: rgba(249,115,22,0.25); }
.mcard-high::after   { background: radial-gradient(ellipse at top, rgba(249,115,22,0.07) 0%, transparent 70%); }
.mcard-med    { border-color: rgba(234,179,8,0.2); }
.mcard-med::after    { background: radial-gradient(ellipse at top, rgba(234,179,8,0.06) 0%, transparent 70%); }
.mcard-low    { border-color: rgba(59,130,246,0.2); }
.mcard-low::after    { background: radial-gradient(ellipse at top, rgba(59,130,246,0.06) 0%, transparent 70%); }

.mcard-val {
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -1px;
  margin-bottom: 0.3rem;
}
.mcard-lbl {
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #475569;
}
.val-total { color: #00b4ff; text-shadow: 0 0 20px rgba(0,180,255,0.4); }
.val-crit  { color: #ef4444; text-shadow: 0 0 20px rgba(239,68,68,0.4); }
.val-high  { color: #f97316; text-shadow: 0 0 20px rgba(249,115,22,0.3); }
.val-med   { color: #eab308; text-shadow: 0 0 20px rgba(234,179,8,0.3); }
.val-low   { color: #3b82f6; text-shadow: 0 0 20px rgba(59,130,246,0.3); }

/* ═══════════════════════════════════════════
   FINDINGS TABLE
═══════════════════════════════════════════ */
[data-testid="stDataFrame"] {
  background: rgba(8,12,24,0.7) !important;
  border: 1px solid rgba(0,180,255,0.1) !important;
  border-radius: 12px !important;
}

/* ═══════════════════════════════════════════
   FINDINGS EXPANDERS
═══════════════════════════════════════════ */
[data-testid="stExpander"] {
  background: rgba(8,12,24,0.6) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
  border-radius: 10px !important;
  margin-bottom: 0.5rem !important;
  backdrop-filter: blur(8px);
}
[data-testid="stExpander"]:hover {
  border-color: rgba(0,180,255,0.15) !important;
}

/* ═══════════════════════════════════════════
   SEVERITY BADGES
═══════════════════════════════════════════ */
.sev-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  margin-right: 0.5rem;
}
.sev-crit { background: rgba(239,68,68,0.15);  color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
.sev-high { background: rgba(249,115,22,0.12); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
.sev-med  { background: rgba(234,179,8,0.10);  color: #eab308; border: 1px solid rgba(234,179,8,0.3); }
.sev-low  { background: rgba(59,130,246,0.10); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3); }

/* ═══════════════════════════════════════════
   CHAT MESSAGES
═══════════════════════════════════════════ */
[data-testid="stChatMessage"] {
  background: rgba(8,12,24,0.7) !important;
  border: 1px solid rgba(0,180,255,0.1) !important;
  border-radius: 12px !important;
  backdrop-filter: blur(8px);
}

/* ═══════════════════════════════════════════
   EGRESS BLOCK
═══════════════════════════════════════════ */
.egress-block {
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.3);
  border-left: 3px solid #ef4444;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.84rem;
  color: #fca5a5;
  margin-bottom: 0.75rem;
}

/* ═══════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════ */
.sb-logo {
  padding: 0.25rem 0 1.25rem;
  border-bottom: 1px solid rgba(0,180,255,0.08);
  margin-bottom: 1.25rem;
}
.sb-logo-title { font-size: 1.15rem; font-weight: 700; color: #f1f5f9; }
.sb-logo-sub { font-size: 0.7rem; color: #475569; margin-top: 0.2rem; }

.sb-section {
  background: rgba(0,180,255,0.03);
  border: 1px solid rgba(0,180,255,0.08);
  border-radius: 10px;
  padding: 0.9rem 1rem;
  margin-bottom: 0.75rem;
}
.sb-section-title {
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #475569;
  margin-bottom: 0.65rem;
}
.sb-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.25rem 0;
  font-size: 0.78rem;
  color: #64748b;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.sb-row:last-child { border-bottom: none; }
.sb-row strong { color: #94a3b8; font-weight: 500; }
.sb-allow { color: #22c55e; font-size: 0.7rem; }
.sb-deny  { color: #ef4444; font-size: 0.7rem; }

/* ═══════════════════════════════════════════
   SECTION HEADERS
═══════════════════════════════════════════ */
hr { border-color: rgba(0,180,255,0.08) !important; margin: 1.5rem 0 !important; }
.section-header {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #475569;
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.section-header::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(0,180,255,0.08);
}

/* ── Chat input — force full area dark ── */
[data-testid="stChatInput"],
[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] textarea,
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
.stChatFloatingInputContainer,
.stChatFloatingInputContainer > div {
  background: #050810 !important;
}
[data-testid="stChatInput"] > div {
  border: 1px solid rgba(0,180,255,0.18) !important;
  border-radius: 12px !important;
}
[data-testid="stChatInput"] textarea {
  color: #f1f5f9 !important;
  font-family: 'Inter', sans-serif !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #334155 !important; }

#MainMenu, footer, [data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sb-logo">
      <div class="sb-logo-title">🛡 SOVA</div>
      <div class="sb-logo-sub">Sovereign Vulnerability Analysis Agent</div>
    </div>

    <div class="sb-section">
      <div class="sb-section-title">Security Boundary</div>
      <div class="sb-row"><strong>Kata VM</strong><span>Hardware-isolated kernel</span></div>
      <div class="sb-row"><strong>OpenShell</strong><span>Egress deny-all</span></div>
      <div class="sb-row"><strong>RHOAI</strong><span>On-prem model endpoint</span></div>
    </div>

    <div class="sb-section">
      <div class="sb-section-title">Network Policy</div>
      <div class="sb-row"><strong>Model endpoint</strong><span class="sb-allow">✓ allowed</span></div>
      <div class="sb-row"><strong>semgrep.dev</strong><span class="sb-allow">✓ allowed</span></div>
      <div class="sb-row"><strong>github.com</strong><span class="sb-allow">✓ allowed</span></div>
      <div class="sb-row"><strong>Everything else</strong><span class="sb-deny">✗ blocked</span></div>
    </div>

    <div class="sb-section">
      <div class="sb-section-title">Scanners</div>
      <div class="sb-row"><strong>Semgrep</strong><span>694 rules</span></div>
      <div class="sb-row"><strong>Bandit</strong><span>Python SAST</span></div>
      <div class="sb-row"><strong>Safety</strong><span>Dep CVE check</span></div>
    </div>

    <div class="sb-section">
      <div class="sb-section-title">Example Targets</div>
    </div>
    """, unsafe_allow_html=True)

    for ex in [
        "github.com/digininja/DVWA",
        "github.com/OWASP/WebGoat-Legacy",
        "github.com/juice-shop/juice-shop",
    ]:
        st.code(f"https://{ex}.git", language=None)

    # ── Scan history ──────────────────────────────────────────────────────────
    if st.session_state.get("scan_history"):
        st.markdown("""
        <div class="sb-section" style="margin-top:0.5rem;">
          <div class="sb-section-title">Recent Scans</div>
        </div>
        """, unsafe_allow_html=True)
        for i, entry in enumerate(st.session_state.scan_history):
            repo_short = entry["url"].split("/")[-1].replace(".git", "")
            risk_col = _risk_color(entry["risk"])
            label = f'`{repo_short}` · risk {entry["risk"]} · {entry["ts"]}'
            if st.button(label, key=f"hist_{i}", use_container_width=True):
                st.session_state.current_sarif = entry["sarif"]
                st.session_state.scan_duration = entry["duration"]
                st.rerun()

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-wrap">
  <div class="hero-grid-text">[ KATA VM ] [ OPENSHELL ] [ RHOAI ]<br>EGRESS POLICY: ENFORCE<br>SANDBOX: ACTIVE</div>
  <div class="hero-eyebrow">Red Hat OpenShift AI · DEMOJam 2027</div>
  <div class="hero-title">Sovereign Vulnerability<br>Analysis Agent</div>
  <div class="hero-sub">
    AI-powered code security scanning that never leaves your cluster.
    Every scan runs inside a hardware-isolated Kata VM with enforced network egress control.
  </div>
  <div class="pill-row">
    <div class="pill"><span class="dot dot-green"></span>Kata VM Active</div>
    <div class="pill"><span class="dot dot-cyan"></span>OpenShell Enforced</div>
    <div class="pill"><span class="dot dot-red"></span>Egress Blocked</div>
    <div class="pill"><span class="dot dot-cyan"></span>Zero Data Leakage</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []
if "current_sarif" not in st.session_state:
    st.session_state.current_sarif = None
if "scan_duration" not in st.session_state:
    st.session_state.scan_duration = None
if "scan_history" not in st.session_state:
    st.session_state.scan_history = []   # list of {url, sarif, duration, risk, ts}
if "egress_blocked" not in st.session_state:
    st.session_state.egress_blocked = False

# ── Scan input ────────────────────────────────────────────────────────────────
st.markdown('<div class="scan-label">Repository URL</div>', unsafe_allow_html=True)
col_input, col_btn = st.columns([5, 1])
with col_input:
    git_url = st.text_input(
        "repo",
        placeholder="https://github.com/org/repo.git",
        label_visibility="collapsed",
    )
with col_btn:
    scan_clicked = st.button("Scan →", type="primary", use_container_width=True)

if scan_clicked and git_url:
    is_valid, error_msg = validate_git_url(git_url)
    if not is_valid:
        st.error(f"Invalid URL: {error_msg}")
    else:
        prompt = f"""@security-analyst Scan this repository: {git_url}

Follow the Security Analyst workflow from /sandbox/.agents/security-analyst.md:
1. Use python3 vuln_scan.py clone --url {git_url} --dest /sandbox/tmp/scan
2. Use python3 vuln_scan.py semgrep --path /sandbox/tmp/scan --output /sandbox/tmp/semgrep.sarif
3. Use python3 vuln_scan.py bandit --path /sandbox/tmp/scan --output /sandbox/tmp/bandit.json

CRITICAL: Extract COUNTS ONLY - do NOT read detailed findings:
- Total vulnerabilities: `jq '.runs[0].results | length' /sandbox/tmp/semgrep.sarif`
- By severity: `jq '[.runs[0].results[].level] | group_by(.) | map({{(.[0]): length}}) | add' /sandbox/tmp/semgrep.sarif`
- Top rule IDs: `jq -r '.runs[0].results[].ruleId' /sandbox/tmp/semgrep.sarif | sort | uniq -c | sort -rn | head -5`

Report ONLY: total count, severity breakdown, and top 5 rule IDs (no details, no snippets, no file paths).
"""
        scan_id = str(uuid.uuid4())
        _scan_start = time.time()
        st.session_state.scan_duration = None
        st.session_state.history.append(("user", git_url))

        result_holder: dict = {}

        def _run_scan():
            try:
                result_holder["result"] = run_agent(prompt, scan_id=scan_id)
            except Exception as exc:
                result_holder["error"] = str(exc)

        scan_thread = threading.Thread(target=_run_scan, daemon=True)
        scan_thread.start()

        # Step display config: key → (label, fallback_timeout_secs)
        STEP_CFG = {
            "clone":    ("Cloning repository into sandbox",                            60),
            "semgrep":  ("Semgrep · 694 rules (OWASP · p/python · p/security-audit)", 180),
            "bandit":   ("Bandit · Python security analysis",                          60),
            "analysis": ("AI agent synthesizing findings",                              90),
        }
        step_keys = list(STEP_CFG.keys())

        def _fmt_running(label):
            return f'<span style="color:#64748b;font-size:0.88rem;">⟳ &nbsp;{label}…</span>'

        def _fmt_done(label, detail=None):
            suffix = f' <span style="color:#475569;font-size:0.78rem;">· {detail}</span>' if detail else ""
            return f'<span style="color:#22c55e;font-size:0.88rem;">✓ &nbsp;{label}{suffix}</span>'

        def _fmt_fail(label, detail=None):
            suffix = f' <span style="color:#475569;font-size:0.78rem;">· {detail}</span>' if detail else ""
            return f'<span style="color:#ef4444;font-size:0.88rem;">✗ &nbsp;{label}{suffix}</span>'

        with st.status("Scanning inside Kata VM sandbox…", expanded=True) as scan_status:
            placeholders = {k: st.empty() for k in step_keys}

            seen: dict = {}   # step -> latest event
            current_step_idx = 0

            # Show first step as running immediately
            first_key = step_keys[0]
            first_label = STEP_CFG[first_key][0]
            placeholders[first_key].markdown(_fmt_running(first_label), unsafe_allow_html=True)

            deadline = time.time() + sum(t for _, t in STEP_CFG.values()) + 30

            while scan_thread.is_alive() and time.time() < deadline:
                events = _poll_progress(scan_id)
                for ev in events:
                    k = ev["step"]
                    seen[k] = ev

                for i, key in enumerate(step_keys):
                    label, _ = STEP_CFG[key]
                    ev = seen.get(key)
                    if ev is None:
                        if i == current_step_idx:
                            placeholders[key].markdown(_fmt_running(label), unsafe_allow_html=True)
                        continue
                    if ev["status"] == "started":
                        current_step_idx = i
                        placeholders[key].markdown(_fmt_running(label), unsafe_allow_html=True)
                        # Mark next step as waiting
                        if i + 1 < len(step_keys):
                            nk = step_keys[i + 1]
                            if nk not in seen:
                                nl, _ = STEP_CFG[nk]
                                placeholders[nk].markdown(_fmt_running(nl), unsafe_allow_html=True)
                    elif ev["status"] == "completed":
                        placeholders[key].markdown(_fmt_done(label, ev.get("detail")), unsafe_allow_html=True)
                    elif ev["status"] == "failed":
                        placeholders[key].markdown(_fmt_fail(label, ev.get("detail")), unsafe_allow_html=True)

                time.sleep(1)

            scan_thread.join()

            # Final pass — mark anything not yet shown
            events = _poll_progress(scan_id)
            for ev in events:
                seen[ev["step"]] = ev
            for key in step_keys:
                label, _ = STEP_CFG[key]
                ev = seen.get(key)
                if ev and ev["status"] == "completed":
                    placeholders[key].markdown(_fmt_done(label, ev.get("detail")), unsafe_allow_html=True)
                elif ev and ev["status"] == "failed":
                    placeholders[key].markdown(_fmt_fail(label, ev.get("detail")), unsafe_allow_html=True)

            elapsed = time.time() - _scan_start
            mins, secs = divmod(int(elapsed), 60)
            duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"

            if "error" in result_holder:
                scan_status.update(label="Scan failed", state="error", expanded=True)
                st.error(result_holder["error"])
            else:
                scan_status.update(
                    label=f"Scan complete · {duration_str}",
                    state="complete", expanded=False,
                )
                st.session_state.scan_duration = duration_str
                result = result_holder.get("result")
                if result:
                    st.session_state.history.append(("assistant", result))
                    st.session_state.egress_blocked = result.egress_blocked
                    if result.sarif_data:
                        st.session_state.current_sarif = result.sarif_data
                        sc_tmp = parse_sarif(result.sarif_data)["severity_counts"]
                        entry = {
                            "url": git_url,
                            "sarif": result.sarif_data,
                            "duration": duration_str,
                            "risk": _risk_score(sc_tmp),
                            "ts": time.strftime("%H:%M"),
                        }
                        st.session_state.scan_history = (
                            [entry] + st.session_state.scan_history
                        )[:5]

# ── SARIF Dashboard ───────────────────────────────────────────────────────────
if st.session_state.current_sarif:
    sarif_metrics = parse_sarif(st.session_state.current_sarif)
    total = sarif_metrics["total"]
    sc = sarif_metrics["severity_counts"]

    risk = _risk_score(sc)
    risk_col = _risk_color(risk)
    risk_lbl = "CRITICAL" if risk >= 75 else "HIGH" if risk >= 45 else "MEDIUM" if risk >= 20 else "LOW"
    duration_html = (
        f'<span style="font-size:0.75rem;color:#475569;margin-left:0.75rem;">· {st.session_state.scan_duration}</span>'
        if st.session_state.scan_duration else ""
    )

    st.markdown(
        f'<div class="section-header">Scan Results{duration_html}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(f"""
    <div class="metrics-row">
      <div class="mcard" style="border-color:{risk_col}33;flex:1.2;">
        <div style="font-size:0.6rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:{risk_col};margin-bottom:0.2rem;">{risk_lbl} RISK</div>
        <div class="mcard-val" style="color:{risk_col};text-shadow:0 0 20px {risk_col}66;">{risk}</div>
        <div class="mcard-lbl">Risk Score</div>
      </div>
      <div class="mcard mcard-total">
        <div class="mcard-val val-total">{total}</div>
        <div class="mcard-lbl">Total</div>
      </div>
      <div class="mcard mcard-crit">
        <div class="mcard-val val-crit">{sc['critical']}</div>
        <div class="mcard-lbl">Critical</div>
      </div>
      <div class="mcard mcard-high">
        <div class="mcard-val val-high">{sc['high']}</div>
        <div class="mcard-lbl">High</div>
      </div>
      <div class="mcard mcard-med">
        <div class="mcard-val val-med">{sc['medium']}</div>
        <div class="mcard-lbl">Medium</div>
      </div>
      <div class="mcard mcard-low">
        <div class="mcard-val val-low">{sc['low']}</div>
        <div class="mcard-lbl">Low</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── On-prem callout ───────────────────────────────────────────────────────
    blocked_extra = " · egress attempt detected and blocked" if st.session_state.get("egress_blocked") else ""
    st.markdown(f"""
    <div style="background:rgba(34,197,94,0.04);border:1px solid rgba(34,197,94,0.15);
                border-left:3px solid #22c55e;border-radius:8px;
                padding:0.65rem 1rem;margin-bottom:1rem;
                display:flex;align-items:center;gap:1.5rem;flex-wrap:wrap;">
      <span style="font-size:0.78rem;font-weight:600;color:#22c55e;">🔒 Data stayed on-prem</span>
      <span style="font-size:0.75rem;color:#475569;">✓ Model endpoint &nbsp;·&nbsp; ✓ semgrep.dev &nbsp;·&nbsp; ✓ github.com</span>
      <span style="font-size:0.75rem;color:#ef4444;">✗ All other egress blocked{blocked_extra}</span>
    </div>
    """, unsafe_allow_html=True)

    if total > 0:
        col_left, col_right = st.columns([1, 2])

        with col_left:
            labels = ["Critical", "High", "Medium", "Low"]
            values = [sc["critical"], sc["high"], sc["medium"], sc["low"]]
            colors = ["#ef4444", "#f97316", "#eab308", "#3b82f6"]

            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                marker=dict(
                    colors=colors,
                    line=dict(color="#050810", width=3),
                ),
                hole=0.65,
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>%{value} findings (%{percent})<extra></extra>",
            )])
            fig.update_layout(
                height=280,
                margin=dict(t=20, b=20, l=20, r=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(
                    font=dict(color="#64748b", size=11, family="Inter"),
                    bgcolor="rgba(0,0,0,0)",
                    x=1, y=0.5, xanchor="left", yanchor="middle",
                ),
                annotations=[dict(
                    text=f"<b>{total}</b>",
                    x=0.5, y=0.5, showarrow=False,
                    font=dict(size=28, color="#00b4ff", family="Inter"),
                )],
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            if sarif_metrics["findings"]:
                df = pd.DataFrame(sarif_metrics["findings"])

                # Top 5 rules bar chart
                rule_counts = (
                    df.groupby("rule_id")
                    .agg(count=("rule_id", "count"), severity=("severity", "first"))
                    .reset_index()
                    .sort_values("count", ascending=False)
                    .head(5)
                )
                sev_color_map = {
                    "critical": "#ef4444", "high": "#f97316",
                    "medium": "#eab308", "low": "#3b82f6",
                }
                bar_colors = [sev_color_map.get(s, "#64748b") for s in rule_counts["severity"]]

                bar_fig = go.Figure(go.Bar(
                    x=rule_counts["count"],
                    y=rule_counts["rule_id"],
                    orientation="h",
                    marker=dict(color=bar_colors, opacity=0.85),
                    text=rule_counts["count"],
                    textposition="outside",
                    textfont=dict(color="#94a3b8", size=11),
                    hovertemplate="<b>%{y}</b><br>%{x} findings<extra></extra>",
                ))
                bar_fig.update_layout(
                    height=280,
                    margin=dict(t=10, b=10, l=10, r=40),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, color="#475569"),
                    yaxis=dict(
                        color="#94a3b8", tickfont=dict(size=10, family="JetBrains Mono"),
                        autorange="reversed",
                    ),
                    bargap=0.35,
                )
                st.plotly_chart(bar_fig, use_container_width=True)

        # ── Files by finding count ────────────────────────────────────────────
        st.markdown("""<div class="section-header" style="margin-top:1.25rem">Hotspot Files</div>""", unsafe_allow_html=True)
        file_counts = (
            df.groupby("file")
            .agg(count=("file", "count"))
            .reset_index()
            .sort_values("count", ascending=False)
            .head(8)
        )
        file_counts["short"] = file_counts["file"].apply(
            lambda p: ("…/" + "/".join(p.split("/")[-2:])) if p.count("/") > 1 else p
        )
        hf_fig = go.Figure(go.Bar(
            x=file_counts["count"],
            y=file_counts["short"],
            orientation="h",
            marker=dict(color="rgba(0,180,255,0.5)", line=dict(color="rgba(0,180,255,0.8)", width=1)),
            text=file_counts["count"],
            textposition="outside",
            textfont=dict(color="#94a3b8", size=10),
            hovertext=file_counts["file"],
            hovertemplate="<b>%{hovertext}</b><br>%{x} findings<extra></extra>",
        ))
        hf_fig.update_layout(
            height=220,
            margin=dict(t=5, b=5, l=5, r=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(color="#64748b", tickfont=dict(size=9, family="JetBrains Mono"), autorange="reversed"),
            bargap=0.3,
        )
        st.plotly_chart(hf_fig, use_container_width=True)

        # ── Findings drill-down ───────────────────────────────────────────────
        st.markdown("""<div class="section-header" style="margin-top:0.5rem">Findings</div>""", unsafe_allow_html=True)

        if "rule_filter" not in st.session_state:
            st.session_state.rule_filter = "All rules"

        all_rules = sorted(df["rule_id"].unique().tolist())
        top5_rules = (
            df["rule_id"].value_counts().head(5).index.tolist()
        )
        filter_options = ["All rules"] + top5_rules + [r for r in all_rules if r not in top5_rules]

        selected_rule = st.selectbox(
            "Filter by rule",
            filter_options,
            index=filter_options.index(st.session_state.rule_filter)
                  if st.session_state.rule_filter in filter_options else 0,
            label_visibility="collapsed",
        )
        st.session_state.rule_filter = selected_rule

        filtered = (
            sarif_metrics["findings"] if selected_rule == "All rules"
            else [f for f in sarif_metrics["findings"] if f["rule_id"] == selected_rule]
        )

        shown = filtered[:20]
        if selected_rule != "All rules":
            st.markdown(
                f'<div style="font-size:0.78rem;color:#475569;margin-bottom:0.5rem;">'
                f'{len(filtered)} finding{"s" if len(filtered)!=1 else ""} for '
                f'<code style="color:#00b4ff">{selected_rule}</code></div>',
                unsafe_allow_html=True,
            )

        sev_cls = {"critical": "sev-crit", "high": "sev-high", "medium": "sev-med", "low": "sev-low"}
        sev_lbl = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

        for finding in shown:
            sev = finding["severity"]
            title = f"{finding['file']}:{finding['line']}"
            with st.expander(title):
                col_a, col_b = st.columns([1, 3])
                with col_a:
                    st.markdown(
                        f'<span class="sev-badge {sev_cls.get(sev, "sev-low")}">'
                        f'{sev_lbl.get(sev, sev.upper())}</span>',
                        unsafe_allow_html=True,
                    )
                with col_b:
                    cwe_url, cwe_id = _cwe_url(finding["rule_id"])
                    cwe_html = (
                        f' <a href="{cwe_url}" target="_blank" '
                        f'style="color:#64748b;font-size:0.72rem;text-decoration:none;'
                        f'border:1px solid #334155;border-radius:3px;padding:1px 5px;margin-left:4px;">'
                        f'CWE-{cwe_id} ↗</a>'
                        if cwe_url else ""
                    )
                    st.markdown(
                        f'<code style="color:#00b4ff;font-size:0.82rem;">{finding["rule_id"]}</code>'
                        f'{cwe_html}'
                        f'<span style="color:#475569;font-size:0.78rem;"> · via {finding["tool"]}</span>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**{finding['message']}**")
                if finding["snippet"]:
                    st.code(finding["snippet"], language="python")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.download_button(
        label="Download SARIF Report",
        data=json.dumps(st.session_state.current_sarif, indent=2),
        file_name="sova-report.sarif",
        mime="application/json",
    )

# ── Agent conversation ────────────────────────────────────────────────────────
if st.session_state.history:
    st.markdown("""<div class="section-header" style="margin-top:1.5rem">Agent Output</div>""", unsafe_allow_html=True)
    for role, item in st.session_state.history:
        if role == "user":
            with st.chat_message("user"):
                st.markdown(f"`{item}`")
        else:
            with st.chat_message("assistant"):
                if item.egress_blocked:
                    st.markdown("""
                    <div class="egress-block">
                      🚫 <strong>Egress blocked by OpenShell</strong> — agent attempted to reach a non-allowlisted host. Connection denied by policy.
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown(item.text)

# ── Custom prompt ─────────────────────────────────────────────────────────────
st.chat_input("Send a custom prompt to the security agent...")
