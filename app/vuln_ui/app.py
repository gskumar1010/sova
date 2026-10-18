"""SOVA Vulnerability Dashboard UI. Presentation layer over the sandboxed agent."""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json

from agent_client import run_agent, validate_git_url, parse_sarif

st.set_page_config(
    page_title="SOVA — Sovereign Vulnerability Analysis Agent",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  /* ── base ── */
  [data-testid="stAppViewContainer"] { background: #0d1117; }
  [data-testid="stSidebar"] { background: #161b22; border-right: 1px solid #30363d; }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { padding-top: 1.5rem; }

  /* ── typography ── */
  html, body, [class*="css"] { color: #e6edf3; font-family: "Red Hat Display", "Segoe UI", sans-serif; }
  h1, h2, h3 { color: #e6edf3 !important; }

  /* ── hero header ── */
  .sova-hero {
    background: linear-gradient(135deg, #161b22 0%, #0d1117 60%, #1a0a0a 100%);
    border: 1px solid #30363d;
    border-left: 4px solid #ee0000;
    border-radius: 8px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
  }
  .sova-hero-title {
    font-size: 2rem;
    font-weight: 700;
    color: #e6edf3;
    letter-spacing: -0.5px;
    margin: 0;
    line-height: 1.1;
  }
  .sova-hero-title span { color: #ee0000; }
  .sova-hero-sub {
    font-size: 0.85rem;
    color: #8b949e;
    margin: 0.3rem 0 0;
  }
  .sova-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 0.25rem 0.75rem;
    font-size: 0.72rem;
    color: #8b949e;
    margin-top: 0.5rem;
    margin-right: 0.4rem;
  }
  .sova-badge .dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #3fb950; display: inline-block;
    box-shadow: 0 0 6px #3fb950;
  }
  .sova-badge .dot-red { background: #ee0000; box-shadow: 0 0 6px #ee0000; }

  /* ── metric cards ── */
  .metric-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    text-align: center;
  }
  .metric-card .val { font-size: 2.25rem; font-weight: 700; line-height: 1; }
  .metric-card .lbl { font-size: 0.75rem; color: #8b949e; margin-top: 0.3rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .metric-total .val { color: #e6edf3; }
  .metric-crit  .val { color: #f85149; }
  .metric-high  .val { color: #ff7b72; }
  .metric-med   .val { color: #e3b341; }
  .metric-low   .val { color: #58a6ff; }

  /* ── scan input area ── */
  .scan-panel {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
  }
  .scan-panel-label {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8b949e;
    margin-bottom: 0.5rem;
  }
  [data-testid="stTextInput"] > div > div > input {
    background: #0d1117 !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
    border-radius: 6px !important;
  }
  [data-testid="stTextInput"] > div > div > input:focus {
    border-color: #ee0000 !important;
    box-shadow: 0 0 0 2px rgba(238,0,0,0.2) !important;
  }
  [data-testid="stButton"] > button[kind="primary"] {
    background: #ee0000 !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
    padding: 0.5rem 1.5rem !important;
  }
  [data-testid="stButton"] > button[kind="primary"]:hover {
    background: #cc0000 !important;
  }

  /* ── findings table ── */
  [data-testid="stDataFrame"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
  }

  /* ── expanders (findings) ── */
  [data-testid="stExpander"] {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px !important;
    margin-bottom: 0.4rem;
  }

  /* ── chat messages ── */
  [data-testid="stChatMessage"] {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    border-radius: 8px !important;
  }

  /* ── egress block banner ── */
  .egress-block {
    background: #1a0a0a;
    border: 1px solid #ee0000;
    border-left: 4px solid #ee0000;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    color: #f85149;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
  }

  /* ── sidebar ── */
  .sidebar-section {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.75rem;
    font-size: 0.82rem;
  }
  .sidebar-section h4 {
    color: #8b949e;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 0 0 0.5rem;
    color: #8b949e !important;
  }
  .sidebar-section p { margin: 0.2rem 0; color: #8b949e; }
  .sidebar-section strong { color: #e6edf3; }

  /* ── divider ── */
  hr { border-color: #30363d !important; }

  /* ── status indicator ── */
  .status-live {
    display: inline-flex; align-items: center; gap: 0.4rem;
    font-size: 0.75rem; color: #3fb950;
  }
  .pulse {
    width: 8px; height: 8px; border-radius: 50%;
    background: #3fb950;
    animation: pulse 1.5s infinite;
    display: inline-block;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(63,185,80,0.4); }
    50% { opacity: 0.7; box-shadow: 0 0 0 4px rgba(63,185,80,0); }
  }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding: 0.5rem 0 1rem;">
      <div style="font-size:1.1rem;font-weight:700;color:#e6edf3;">🛡 SOVA</div>
      <div style="font-size:0.72rem;color:#8b949e;">Sovereign Vulnerability Analysis Agent</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="sidebar-section">
      <h4>Security Boundary</h4>
      <p><strong>Kata VM</strong> · Hardware-isolated guest kernel</p>
      <p><strong>OpenShell</strong> · Egress deny-all policy</p>
      <p><strong>RHOAI</strong> · On-prem model endpoint</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="sidebar-section">
      <h4>Allowed Egress</h4>
      <p>✅ Model endpoint (MaaS)</p>
      <p>✅ semgrep.dev (rule registry)</p>
      <p>✅ github.com (git clone)</p>
      <p>🚫 Everything else — blocked</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="sidebar-section">
      <h4>Scanners</h4>
      <p><strong>Semgrep</strong> · 694 rules (OWASP, p/python, p/security-audit)</p>
      <p><strong>Bandit</strong> · Python security analysis</p>
      <p><strong>Safety</strong> · Dependency CVE check</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="sidebar-section">
      <h4>Example Targets</h4>
    </div>
    """, unsafe_allow_html=True)
    examples = [
        "https://github.com/digininja/DVWA.git",
        "https://github.com/OWASP/WebGoat-Legacy.git",
        "https://github.com/juice-shop/juice-shop.git",
    ]
    for ex in examples:
        st.code(ex, language=None)

# ── Hero Header ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="sova-hero">
  <div style="font-size:2.5rem;">🛡</div>
  <div>
    <div class="sova-hero-title"><span>SOVA</span> — Sovereign Vulnerability Analysis Agent</div>
    <div class="sova-hero-sub">
      AI-powered code security scanning · Zero data egress · On-prem Red Hat OpenShift AI
    </div>
    <div style="margin-top:0.6rem;">
      <span class="sova-badge"><span class="dot"></span>Kata VM Active</span>
      <span class="sova-badge"><span class="dot"></span>OpenShell Enforced</span>
      <span class="sova-badge"><span class="dot-red dot"></span>Egress Blocked</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []
if "current_sarif" not in st.session_state:
    st.session_state.current_sarif = None

# ── Scan Input ────────────────────────────────────────────────────────────────
col_input, col_btn = st.columns([5, 1])
with col_input:
    git_url = st.text_input(
        "Repository URL",
        placeholder="https://github.com/org/repo.git",
        label_visibility="collapsed",
    )
with col_btn:
    scan_clicked = st.button("Scan", type="primary", use_container_width=True)

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
        st.session_state.history.append(("user", git_url))

        with st.spinner("Agent scanning inside Kata VM sandbox..."):
            try:
                result = run_agent(prompt)
                st.session_state.history.append(("assistant", result))
                if result.sarif_data:
                    st.session_state.current_sarif = result.sarif_data
            except Exception as e:
                st.error(f"Agent error: {str(e)}")

# ── SARIF Dashboard ───────────────────────────────────────────────────────────
if st.session_state.current_sarif:
    sarif_metrics = parse_sarif(st.session_state.current_sarif)

    st.markdown("<hr>", unsafe_allow_html=True)

    # Metric cards
    cols = st.columns(5)
    cards = [
        ("metric-total", sarif_metrics["total"], "Total"),
        ("metric-crit",  sarif_metrics["severity_counts"]["critical"], "Critical"),
        ("metric-high",  sarif_metrics["severity_counts"]["high"],     "High"),
        ("metric-med",   sarif_metrics["severity_counts"]["medium"],   "Medium"),
        ("metric-low",   sarif_metrics["severity_counts"]["low"],      "Low"),
    ]
    for col, (cls, val, lbl) in zip(cols, cards):
        with col:
            st.markdown(f"""
            <div class="metric-card {cls}">
              <div class="val">{val}</div>
              <div class="lbl">{lbl}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)

    if sarif_metrics["total"] > 0:
        col_left, col_right = st.columns([1, 2])

        with col_left:
            severity_data = sarif_metrics["severity_counts"]
            labels = [k.capitalize() for k in severity_data.keys()]
            values = list(severity_data.values())
            colors = ["#f85149", "#ff7b72", "#e3b341", "#58a6ff"]

            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors, line=dict(color="#0d1117", width=2)),
                hole=0.55,
                textfont=dict(color="#e6edf3", size=13),
                hovertemplate="<b>%{label}</b><br>%{value} findings<br>%{percent}<extra></extra>",
            )])
            fig.update_layout(
                height=300,
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(font=dict(color="#8b949e"), bgcolor="rgba(0,0,0,0)"),
                annotations=[dict(
                    text=f"<b>{sarif_metrics['total']}</b><br><span style='font-size:10px'>findings</span>",
                    x=0.5, y=0.5, showarrow=False,
                    font=dict(size=18, color="#e6edf3"),
                )],
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            if sarif_metrics["findings"]:
                findings_df = pd.DataFrame(sarif_metrics["findings"])
                display_df = findings_df[["severity", "rule_id", "file", "line", "message"]].copy()
                display_df.columns = ["Severity", "Rule", "File", "Line", "Message"]
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    height=300,
                    hide_index=True,
                )

        # Detailed findings
        st.markdown("### Findings")
        severity_color = {"critical": "#f85149", "high": "#ff7b72", "medium": "#e3b341", "low": "#58a6ff"}
        severity_label = {"critical": "CRIT", "high": "HIGH", "medium": "MED", "low": "LOW"}

        for finding in sarif_metrics["findings"][:10]:
            sev = finding["severity"]
            color = severity_color.get(sev, "#8b949e")
            badge = severity_label.get(sev, sev.upper())
            header = f'<span style="color:{color};font-weight:700;font-size:0.75rem;background:rgba(0,0,0,0.3);padding:1px 6px;border-radius:3px;border:1px solid {color}33;">{badge}</span> &nbsp; {finding["rule_id"]} — <span style="color:#8b949e;font-size:0.9rem;">{finding["file"]}:{finding["line"]}</span>'
            with st.expander(finding["rule_id"] + " — " + finding["file"]):
                st.markdown(f"{header}", unsafe_allow_html=True)
                st.markdown(f"**Message:** {finding['message']}")
                st.markdown(f"**Tool:** `{finding['tool']}`")
                if finding["snippet"]:
                    st.code(finding["snippet"], language="python")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.download_button(
        label="Download SARIF Report",
        data=json.dumps(st.session_state.current_sarif, indent=2),
        file_name="sova-vulnerability-report.sarif",
        mime="application/json",
    )

# ── Conversation history ──────────────────────────────────────────────────────
if st.session_state.history:
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("### Agent Output")
    for role, item in st.session_state.history:
        if role == "user":
            with st.chat_message("user"):
                st.markdown(f"Scan: `{item}`")
        else:
            with st.chat_message("assistant"):
                if item.egress_blocked:
                    st.markdown("""
                    <div class="egress-block">
                      🚫 <strong>Egress blocked by OpenShell</strong> — the agent attempted to reach a non-allowlisted host. Connection denied.
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown(item.text)

# ── Custom prompt ─────────────────────────────────────────────────────────────
prompt = st.chat_input("Send a custom security analysis prompt to the agent...")
if prompt:
    st.session_state.history.append(("user", prompt))
    with st.spinner("Agent working inside sandbox..."):
        try:
            result = run_agent(prompt)
            st.session_state.history.append(("assistant", result))
            if result.sarif_data:
                st.session_state.current_sarif = result.sarif_data
        except Exception as e:
            st.error(f"Agent error: {str(e)}")
