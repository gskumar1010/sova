# app/vuln_ui/app.py
"""SOVA Vulnerability Dashboard UI. Presentation layer over the sandboxed agent."""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import json

# Streamlit puts this script's own directory on sys.path[0], so import the
# sibling module directly.
from agent_client import run_agent, validate_git_url, parse_sarif


st.set_page_config(page_title="SOVA - Vulnerability Scanner", page_icon="🔒", layout="wide")

st.title("🔒 SOVA - Sovereign Vulnerability Analysis Agent")
st.caption(
    "An AI-powered vulnerability scanner running inside a Kata VM under an OpenShell egress policy. "
    "It can reach the vulnerability orchestrator and the model endpoint - nothing else."
)

with st.expander("Try an example"):
    st.write("- *Scan this repository: https://github.com/OWASP/WebGoat-Legacy.git*")
    st.write("- *Analyze vulnerabilities in https://github.com/digininja/DVWA.git*")
    st.write("- *Run this and show me the raw output: `curl -s http://example.com`* (watch OpenShell block the egress)")

if "history" not in st.session_state:
    st.session_state.history = []

if "current_sarif" not in st.session_state:
    st.session_state.current_sarif = None

# Git URL input
git_url = st.text_input(
    "Repository URL",
    placeholder="https://github.com/user/repo.git",
    help="Enter a Git repository URL from GitHub, GitLab, or Bitbucket"
)

# Scan button
if st.button("🔍 Scan Repository", type="primary") and git_url:
    # Validate URL
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
        st.session_state.history.append(("user", prompt))

        with st.spinner("Agent scanning repository inside the sandbox..."):
            try:
                result = run_agent(prompt)
                st.session_state.history.append(("assistant", result))

                # Store SARIF data if available
                if result.sarif_data:
                    st.session_state.current_sarif = result.sarif_data
            except Exception as e:
                st.error(f"Error running agent: {str(e)}")
                import traceback
                st.code(traceback.format_exc())

# Custom prompt input (for advanced users)
prompt = st.chat_input("Or enter a custom security analysis prompt...")
if prompt:
    st.session_state.history.append(("user", prompt))
    with st.spinner("Agent working inside the sandbox..."):
        try:
            result = run_agent(prompt)
            st.session_state.history.append(("assistant", result))

            if result.sarif_data:
                st.session_state.current_sarif = result.sarif_data
        except Exception as e:
            st.error(f"Error running agent: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

# Display conversation history
for role, item in st.session_state.history:
    if role == "user":
        with st.chat_message("user"):
            st.write(item)
    else:
        with st.chat_message("assistant"):
            if item.egress_blocked:
                st.error("🚫 Egress blocked by OpenShell policy - the agent could not reach a non-allowlisted host.")
            st.write(item.text)

# Display SARIF dashboard if available
if st.session_state.current_sarif:
    st.divider()
    st.subheader("📊 Vulnerability Analysis Dashboard")

    sarif_metrics = parse_sarif(st.session_state.current_sarif)

    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Vulnerabilities", sarif_metrics["total"])
    with col2:
        st.metric("🔴 Critical", sarif_metrics["severity_counts"]["critical"])
    with col3:
        st.metric("🟠 High", sarif_metrics["severity_counts"]["high"])
    with col4:
        st.metric("🟡 Medium", sarif_metrics["severity_counts"]["medium"])
    with col5:
        st.metric("🔵 Low", sarif_metrics["severity_counts"]["low"])

    # Severity breakdown pie chart
    if sarif_metrics["total"] > 0:
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Severity Distribution")
            severity_data = sarif_metrics["severity_counts"]
            fig = go.Figure(data=[go.Pie(
                labels=list(severity_data.keys()),
                values=list(severity_data.values()),
                marker=dict(colors=["#ff4444", "#ff8800", "#ffbb00", "#4488ff"]),
                hole=0.3
            )])
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.subheader("Vulnerability Findings")
            if sarif_metrics["findings"]:
                # Create findings table
                findings_df = pd.DataFrame(sarif_metrics["findings"])
                # Display sortable table
                st.dataframe(
                    findings_df[["severity", "rule_id", "file", "line", "message"]],
                    use_container_width=True,
                    height=400
                )

    # Detailed findings
    st.subheader("🔍 Detailed Findings")
    for idx, finding in enumerate(sarif_metrics["findings"][:10]):  # Show top 10
        severity_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🔵"
        }
        with st.expander(f"{severity_emoji.get(finding['severity'], '⚪')} {finding['rule_id']} - {finding['file']}:{finding['line']}"):
            st.write(f"**Severity**: {finding['severity'].upper()}")
            st.write(f"**Tool**: {finding['tool']}")
            st.write(f"**Message**: {finding['message']}")
            if finding['snippet']:
                st.code(finding['snippet'], language="python")

    # Download SARIF button
    st.download_button(
        label="📥 Download SARIF Report",
        data=json.dumps(st.session_state.current_sarif, indent=2),
        file_name="vulnerability_report.sarif",
        mime="application/json"
    )
