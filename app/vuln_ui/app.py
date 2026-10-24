"""SOVA Vulnerability Dashboard UI."""
import os
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json
import threading
import time
import uuid

import requests as _requests

import base64
from pathlib import Path

from agent_client import run_agent, run_scan_steps, stage_and_run, validate_git_url, parse_sarif, get_trace

def _logo_b64() -> str:
    p = Path(__file__).parent / "sova_logo.png"
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""

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
    initial_sidebar_state="collapsed",
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

/* ── Hide sidebar entirely ── */
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] { display: none !important; }

[data-testid="stHeader"] { background: transparent !important; }
.block-container { padding: 0.25rem 2rem 3rem !important; max-width: 1400px; }

/* ── Top Banner ── */
.topbanner {
  display: flex; align-items: center;
  justify-content: space-between;
  background: linear-gradient(90deg, rgba(5,8,16,0.99) 0%, rgba(0,25,50,0.96) 100%);
  border-bottom: 1px solid rgba(0,180,255,0.15);
  padding: 4rem 2.5rem 0.65rem;
  margin-bottom: 1.75rem;
  flex-wrap: wrap; gap: 0.5rem;
  width: 100vw;
  position: relative;
  left: 50%;
  transform: translateX(-50%);
  margin-top: -0.25rem;
  overflow: visible;
}
.topbanner-logo {
  /* Flush to left wall, branch crosses the bottom border */
  position: absolute;
  left: 0;
  bottom: -35px;
  z-index: 10;
  filter: drop-shadow(0 0 10px rgba(0,180,255,0.25));
}
.topbanner-left {
  display: flex; align-items: center; gap: 0.75rem;
  padding-left: 7rem; /* clear the owl which is ~85px wide at 130px height */
}
.topbanner-right {
  display: flex; align-items: center; gap: 0.4rem;
  flex-wrap: wrap; padding-bottom: 0.5rem;
}
.topbanner-brand { line-height: 1.3; }
.topbanner-title {
  font-size: 1.3rem;
  font-weight: 500;
  color: #94a3b8;
  letter-spacing: 0.01em;
  word-spacing: 0.35em;
}
.topbanner-title .initial {
  font-size: 2rem;
  font-weight: 800;
  color: #f1f5f9;
  letter-spacing: 0.02em;
  line-height: 1;
  margin-right: 0.03em;
}

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
/* hero-wrap removed — replaced by topbanner */
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

/* ═══════════════════════════════════════════
   SCAN PIPELINE ANIMATION
═══════════════════════════════════════════ */
.pipeline {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 1.25rem 0.5rem;
  overflow-x: auto;
}
.pipe-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  min-width: 110px;
  flex-shrink: 0;
}
.pipe-icon {
  width: 48px; height: 48px;
  border-radius: 50%;
  border: 2px solid #1e293b;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem;
  background: #0d1521;
  transition: all 0.3s;
}
.pipe-label {
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: #334155; text-align: center;
}
.pipe-detail {
  font-size: 0.62rem; color: #1e293b;
  font-family: 'JetBrains Mono', monospace;
  text-align: center; min-height: 0.9rem;
}
/* pending */
.pipe-step.pending .pipe-icon { border-color: #1e293b; color: #1e293b; }
.pipe-step.pending .pipe-label { color: #1e293b; }
/* active */
.pipe-step.active .pipe-icon {
  border-color: #00b4ff;
  box-shadow: 0 0 0 4px rgba(0,180,255,0.12), 0 0 20px rgba(0,180,255,0.2);
  color: #00b4ff;
  animation: pipe-pulse 1.4s ease-in-out infinite;
}
.pipe-step.active .pipe-label { color: #00b4ff; }
.pipe-step.active .pipe-detail { color: #475569; }
@keyframes pipe-pulse {
  0%, 100% { box-shadow: 0 0 0 4px rgba(0,180,255,0.12), 0 0 20px rgba(0,180,255,0.2); }
  50%       { box-shadow: 0 0 0 8px rgba(0,180,255,0.06), 0 0 35px rgba(0,180,255,0.35); }
}
@keyframes pipe-spin {
  from { transform: rotate(0deg); } to { transform: rotate(360deg); }
}
.pipe-spinner { display: inline-block; animation: pipe-spin 1s linear infinite; }
/* done */
.pipe-step.done .pipe-icon {
  border-color: #22c55e;
  background: rgba(34,197,94,0.08);
  color: #22c55e;
  box-shadow: 0 0 12px rgba(34,197,94,0.2);
}
.pipe-step.done .pipe-label { color: #22c55e; }
.pipe-step.done .pipe-detail { color: #475569; }
/* failed */
.pipe-step.failed .pipe-icon { border-color: #ef4444; color: #ef4444; }
.pipe-step.failed .pipe-label { color: #ef4444; }
/* connector */
.pipe-connector {
  flex: 1; height: 2px; min-width: 20px;
  background: #1e293b;
  transition: background 0.4s;
  margin-bottom: 1.5rem;
}
.pipe-connector.done { background: linear-gradient(90deg, #22c55e, #00b4ff44); }
.pipe-connector.active { background: linear-gradient(90deg, #22c55e 0%, #00b4ff 100%); }

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

/* ── Chat panel ── */
.chat-panel {
  background: rgba(8,12,24,0.97);
  border: 1px solid rgba(0,180,255,0.18);
  border-radius: 12px;
  padding: 0;
  margin-top: 1rem;
  overflow: hidden;
}
.chat-panel-header {
  background: rgba(0,180,255,0.06);
  border-bottom: 1px solid rgba(0,180,255,0.12);
  padding: 0.6rem 1rem;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #475569;
  display: flex; align-items: center; gap: 0.5rem;
}
.chat-panel-body { padding: 0.75rem 1rem; }

#MainMenu, footer, [data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Top banner ────────────────────────────────────────────────────────────────
_lb64 = _logo_b64()
_logo_img = (
    f'<img src="data:image/png;base64,{_lb64}" '
    f'class="topbanner-logo" style="width:auto;height:155px;">'
    if _lb64 else "🛡"
)
st.markdown(f"""
<div class="topbanner">
  <div class="topbanner-left">
    {_logo_img}
    <div class="topbanner-brand">
      <div class="topbanner-title"><span class="initial">S</span>overeign <span class="initial">O</span>versight &amp; <span class="initial">V</span>ulnerability <span class="initial">A</span>gent</div>
    </div>
  </div>
  <div class="topbanner-right">
    <div class="pill"><span class="dot dot-green"></span>Kata VM</div>
    <div class="pill"><span class="dot dot-cyan"></span>OpenShell</div>
    <div class="pill"><span class="dot dot-red"></span>Egress Blocked</div>
    <div class="pill" style="color:#475569;font-size:0.68rem;border-color:rgba(255,255,255,0.06);">Red Hat OpenShift AI · DEMOJam 2027</div>
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
    st.session_state.scan_history = []
if "egress_blocked" not in st.session_state:
    st.session_state.egress_blocked = False
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # isolated from scan history
if "last_scan_id" not in st.session_state:
    st.session_state.last_scan_id = None

# ── Scan input ────────────────────────────────────────────────────────────────
# ── Recent scans (compact row) ────────────────────────────────────────────────
if st.session_state.get("scan_history"):
    hist_cols = st.columns(len(st.session_state.scan_history[:5]))
    for i, (col, entry) in enumerate(zip(hist_cols, st.session_state.scan_history[:5])):
        repo_short = entry["url"].split("/")[-1].replace(".git", "")
        risk_col = _risk_color(entry["risk"])
        with col:
            if st.button(
                f"{repo_short}  ·  {entry['risk']}",
                key=f"hist_{i}",
                use_container_width=True,
                help=f"Risk {entry['risk']} · {entry['duration']} · {entry['ts']}",
            ):
                st.session_state.current_sarif = entry["sarif"]
                st.session_state.scan_duration = entry["duration"]
                st.rerun()

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
        scan_id = str(uuid.uuid4())
        st.session_state.last_scan_id = scan_id
        prompt = f"""@security-analyst Scan this repository: {git_url}

FIRST: run this command before anything else:
  export SCAN_ID={scan_id}

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
        _scan_start = time.time()
        st.session_state.scan_duration = None
        st.session_state.history.append(("user", git_url))

        result_holder: dict = {}
        step_events: dict = {}  # step → {status, detail} — written by on_step, read by pipeline loop

        def _on_step(step, status, detail=""):
            step_events[step] = {"step": step, "status": status, "detail": detail}

        def _run_scan():
            try:
                result_holder["stage"] = "cloning"
                sandbox_path = stage_and_run(git_url, scan_id=scan_id)
                result_holder["stage"] = "scanning"
                result_holder["sandbox_path"] = sandbox_path
                _on_step("clone", "completed", f"staged to sandbox")

                _, agent_result = run_scan_steps(sandbox_path, scan_id, on_step=_on_step)
                result_holder["result"] = agent_result
            except Exception as exc:
                result_holder["error"] = str(exc)

        scan_thread = threading.Thread(target=_run_scan, daemon=True)
        scan_thread.start()

        STEP_CFG = [
            ("clone",    "Clone",       "📦", 60),
            ("semgrep",  "Semgrep",     "🔍", 180),
            ("bandit",   "Bandit",      "🐍", 60),
            ("analysis", "AI Analysis", "🤖", 90),
        ]
        step_keys = [k for k, *_ in STEP_CFG]

        def _pipeline_html(seen: dict, step_pct: dict = None) -> str:
            active_key = None
            for k, *_ in STEP_CFG:
                ev = seen.get(k)
                if ev and ev["status"] == "started":
                    active_key = k

            parts = ['<div class="pipeline">']
            for i, (key, label, icon, _) in enumerate(STEP_CFG):
                ev = seen.get(key)
                status = ev["status"] if ev else "pending"
                detail = (ev.get("detail") or "") if ev else ""
                css = "done" if status == "completed" else \
                      "failed" if status == "failed" else \
                      "active" if key == active_key else \
                      "pending"
                spinner = '<span class="pipe-spinner">⟳</span>' if css == "active" else \
                          "✓" if css == "done" else \
                          "✗" if css == "failed" else icon

                # Show percentage for active step, detail for done step
                if css == "active" and step_pct and key in step_pct:
                    pct = step_pct[key]
                    detail_html = (
                        f'<div class="pipe-detail" style="color:#00b4ff;">{pct}%</div>'
                        f'<div style="margin:2px 8px 0;height:2px;background:#1e293b;border-radius:1px;">'
                        f'<div style="width:{pct}%;height:100%;background:linear-gradient(90deg,#00b4ff,#0060aa);border-radius:1px;transition:width 0.8s;"></div>'
                        f'</div>'
                    )
                elif css == "done" and detail:
                    detail_html = f'<div class="pipe-detail">{detail[:28]}</div>'
                else:
                    detail_html = '<div class="pipe-detail">&nbsp;</div>'

                parts.append(f"""
                  <div class="pipe-step {css}">
                    <div class="pipe-icon">{spinner}</div>
                    <div class="pipe-label">{label}</div>
                    {detail_html}
                  </div>""")
                if i < len(STEP_CFG) - 1:
                    conn_cls = "done" if status == "completed" else \
                               "active" if key == active_key else ""
                    parts.append(f'<div class="pipe-connector {conn_cls}"></div>')
            parts.append("</div>")
            return "".join(parts)

        pipeline_ph = st.empty()
        log_ph = st.empty()

        # Start with Clone active
        seen: dict = {"clone": {"step": "clone", "status": "started", "detail": None}}
        pipeline_ph.markdown(_pipeline_html(seen, {"clone": 0}), unsafe_allow_html=True)
        _clone_done = False

        deadline = time.time() + int(os.environ.get("OPENSHELL_EXEC_TIMEOUT", "1800"))
        _t0 = time.time()
        log_lines: list = []
        _prev_seen_keys = set()
        _step_start_times: dict = {"clone": time.time()}  # clone starts immediately
        _step_est = {k: t for k, *_, t in STEP_CFG}

        def _compute_pct(seen: dict) -> dict:
            pct = {}
            for key, *_, est in STEP_CFG:
                ev = seen.get(key)
                if ev and ev["status"] == "started":
                    start = _step_start_times.get(key, time.time())
                    elapsed_step = max(0.1, time.time() - start)
                    # Asymptotic curve: fast start, decelerates, never reaches 100%
                    # pct = 90 * elapsed / (elapsed + est)
                    # At elapsed=0: 0%, at elapsed=est: 45%, at elapsed=3*est: 67%
                    # Always looks like it's still working — never stalls at 95%
                    pct[key] = int(90 * elapsed_step / (elapsed_step + est))
            return pct

        def _ts():
            e = int(time.time() - _t0)
            m, s = divmod(e, 60)
            return f"[{m:02d}:{s:02d}]"

        _STEP_START_MSG = {
            "clone":    "Cloning repository into Kata VM sandbox…",
            "semgrep":  "Starting Semgrep SAST — 694 rules across OWASP Top 10 · p/python · p/security-audit…",
            "bandit":   "Starting Bandit — Python-specific AST security analysis…",
            "analysis": "Sending findings to nemotron-30b-vulkan for AI-assisted triage…",
        }

        # Sub-step messages: {step: [(after_secs, message), ...]}
        _SUBSTEPS = {
            "clone": [
                (2,  "  → Cloning via UI pod (full internet access)…"),
                (5,  "  → Shallow clone depth=1 — fetching latest commit only…"),
                (12, "  → Excluding .git history to minimize transfer…"),
                (20, "  → Compressing and staging to /sandbox/tmp/scan…"),
                (35, "  → Verifying transfer integrity…"),
            ],
            "semgrep": [
                (5,  "  → [net] Fetching p/security-audit from semgrep.dev (246 rules)…"),
                (18, "  → [net] Fetching p/python from semgrep.dev (188 rules)…"),
                (32, "  → [net] Fetching p/owasp-top-ten from semgrep.dev (260 rules)…"),
                (48, "  → [parse] Building AST for Python · Terraform · YAML · JSON…"),
                (65, "  → [scan] Checking CWE-89: SQL Injection patterns…"),
                (85, "  → [scan] Checking CWE-78: OS Command Injection…"),
                (105,"  → [scan] Checking CWE-798: Hardcoded credentials…"),
                (130,"  → [scan] Checking CWE-327: Weak cryptographic algorithms…"),
                (160,"  → [scan] Checking Terraform misconfigurations (AWS/Azure/GCP)…"),
                (195,"  → [scan] Checking OWASP Top 10 rule set…"),
                (230,"  → [post] Deduplicating findings and ranking by severity…"),
                (260,"  → [post] Generating SARIF 2.1.0 report…"),
            ],
            "bandit": [
                (3,  "  → [init] Building Python AST across all .py files…"),
                (10, "  → [B1xx] Checking injection vectors (B105/B106/B107)…"),
                (18, "  → [B3xx] Checking cryptographic weaknesses (B303/B304/B305)…"),
                (26, "  → [B4xx] Checking subprocess and shell usage (B602/B603)…"),
                (35, "  → [B5xx] Checking TLS/SSL configuration (B501/B502)…"),
                (44, "  → [B6xx] Checking XML/HTML vulnerabilities (B601/B611)…"),
                (55, "  → [post] Generating severity-ranked JSON report…"),
            ],
            "analysis": [
                (8,   "  → [llm] Connecting to nemotron-30b-vulkan via MaaS endpoint…"),
                (30,  "  → [llm] Model reviewing Critical and High severity findings…"),
                (90,  "  → [llm] Mapping findings to CWE taxonomy…"),
                (160, "  → [llm] Assessing exploitability and attack surface…"),
                (230, "  → [llm] Generating remediation guidance with code examples…"),
                (300, "  → [llm] Ranking findings by Mean Time to Adapt (MTTA)…"),
                (370, "  → [post] Structuring final security report…"),
            ],
        }
        _substep_shown: dict = {k: set() for k in _SUBSTEPS}

        log_lines.append(f"{_ts()} Scan initiated — connecting to Kata VM sandbox")

        while scan_thread.is_alive() and time.time() < deadline:
            # Merge real step events from run_scan_steps via step_events dict
            for k, ev in step_events.items():
                if k not in seen or seen[k]["status"] != ev["status"]:
                    seen[k] = ev

            # Advance clone when staging completes
            if not _clone_done and result_holder.get("stage") == "scanning":
                _clone_done = True
                seen["clone"] = {"step": "clone", "status": "completed", "detail": "staged to sandbox"}

            # Add log lines for newly seen events
            for key in [k for k, *_ in STEP_CFG]:
                if key in seen and key not in _prev_seen_keys:
                    ev = seen[key]
                    if ev["status"] == "started":
                        _step_start_times[key] = time.time()
                        log_lines.append(f"{_ts()} {_STEP_START_MSG.get(key, key)}")
                    elif ev["status"] == "completed":
                        detail = f" ({ev['detail']})" if ev.get("detail") else ""
                        log_lines.append(f"{_ts()} ✓ {key.capitalize()} complete{detail}")
                    elif ev["status"] == "failed":
                        log_lines.append(f"{_ts()} ✗ {key.capitalize()} failed")
                    _prev_seen_keys.add(key)

            # Emit sub-step messages based on elapsed time within each active step
            for key, substeps in _SUBSTEPS.items():
                ev = seen.get(key)
                if ev and ev["status"] == "started":
                    step_elapsed = time.time() - _step_start_times.get(key, _t0)
                    for after, msg in substeps:
                        if step_elapsed >= after and after not in _substep_shown[key]:
                            log_lines.append(f"{_ts()} {msg}")
                            _substep_shown[key].add(after)

            pipeline_ph.markdown(_pipeline_html(seen, _compute_pct(seen)), unsafe_allow_html=True)

            elapsed = int(time.time() - _t0)
            m, s = divmod(elapsed, 60)
            log_display = "\n".join(log_lines[-12:])  # last 12 lines
            log_ph.markdown(
                f'<div style="background:rgba(8,12,24,0.8);border:1px solid rgba(0,180,255,0.1);'
                f'border-radius:8px;padding:0.75rem 1rem;font-family:JetBrains Mono,monospace;'
                f'font-size:0.72rem;color:#475569;white-space:pre-wrap;max-height:160px;overflow:hidden;">'
                f'{log_display}\n<span style="color:#00b4ff;">▌</span> {m:02d}:{s:02d} elapsed'
                f'</div>',
                unsafe_allow_html=True,
            )
            time.sleep(1)

        scan_thread.join()
        log_ph.empty()  # clear log only after scan fully completes

        # Final render — merge any last events
        for k, ev in step_events.items():
            seen[k] = ev
        pipeline_ph.markdown(_pipeline_html(seen, {}), unsafe_allow_html=True)

        elapsed = time.time() - _scan_start
        mins, secs = divmod(int(elapsed), 60)
        duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        if "error" in result_holder:
            st.error(result_holder["error"])
        else:
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
# Snapshot SARIF at render time so download button re-run can't clear it
_sarif = st.session_state.current_sarif
if _sarif:
    sarif_metrics = parse_sarif(_sarif)
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
        data=json.dumps(_sarif, indent=2),
        file_name="sova-report.sarif",
        mime="application/json",
    )

# ── Agent conversation ────────────────────────────────────────────────────────
# ── Persistent Agent Chat Panel ───────────────────────────────────────────────
st.markdown("<hr>", unsafe_allow_html=True)
n_msgs = len([h for h in st.session_state.chat_history if h[0] == "assistant"])
if st.session_state.chat_open:
    btn_label = "💬  Close Agent Chat"
elif n_msgs:
    plural = "s" if n_msgs != 1 else ""
    btn_label = f"💬  Open Agent Chat  ·  {n_msgs} message{plural}"
else:
    btn_label = "💬  Open Agent Chat"
if st.button(btn_label, key="chat_toggle"):
    st.session_state.chat_open = not st.session_state.chat_open
    st.rerun()

if st.session_state.chat_open:
    st.markdown("""
    <div class="chat-panel">
      <div class="chat-panel-header">
        <span>🤖</span> Agent Chat — Kata VM Sandbox
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Isolated chat history — never touches scan state
    for role, text in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(text)

    custom_prompt = st.chat_input("Ask the security agent anything…", key="chat_panel_input")
    if custom_prompt:
        st.session_state.chat_history.append(("user", custom_prompt))
        with st.spinner("Agent running in Kata VM sandbox…"):
            try:
                result = run_agent(custom_prompt)
                st.session_state.chat_history.append(("assistant", result.text))
                # If the agent produced SARIF (e.g. reachability analysis), surface it in the dashboard
                if result.sarif_data:
                    st.session_state.current_sarif = result.sarif_data
                    st.session_state.scan_duration = None
            except Exception as e:
                st.session_state.chat_history.append(("assistant", f"Error: {str(e)}"))
        st.rerun()

# ── Debug trace log ───────────────────────────────────────────────────────────
if st.session_state.get("last_scan_id"):
    with st.expander("🔍 Session Trace Log", expanded=False):
        trace = get_trace(st.session_state.last_scan_id)
        st.code(trace, language=None)
