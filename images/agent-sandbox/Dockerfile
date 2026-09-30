# Agent sandbox image for OpenShell + Kata reference architecture
#
# Based on the OpenShell community base sandbox image.
# Adds: Python 3, curl, jq, git, ripgrep, requests, GitPython, OpenCode config,
# and the vulnerability scanning tool + security analyst persona.
#
# Build:
#   podman build -f images/agent-sandbox/Dockerfile \
#     -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .

FROM ghcr.io/nvidia/openshell-community/sandboxes/base:latest

USER root

# Install Python 3.12 from deadsnakes PPA (base image has Python 3.14 which breaks semgrep)
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        gpg-agent \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        curl \
        jq \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Create venv with Python 3.12 and install semgrep/bandit
# Note: Use setuptools<70 because newer versions removed pkg_resources which semgrep needs
RUN python3.12 -m venv /opt/scantools \
    && /opt/scantools/bin/pip install --no-cache-dir \
        'setuptools<70' \
        requests==2.32.3 \
        gitpython==3.1.43 \
        semgrep==1.85.0 \
        bandit==1.7.9

COPY images/agent-sandbox/opencode.json /home/user/.config/opencode/config.json
COPY app/agent_tools/vuln_scan.py /home/user/workspace/vuln_scan.py
COPY images/agent-sandbox/SECURITY_ANALYST.md /home/user/workspace/SECURITY_ANALYST.md
COPY images/agent-sandbox/startup.sh /usr/local/bin/startup.sh

RUN chmod +x /home/user/workspace/vuln_scan.py \
    && chmod -R 755 /home/user/workspace \
    && chmod +x /usr/local/bin/startup.sh

USER user
WORKDIR /home/user/workspace

# Use startup wrapper to auto-stage files to /sandbox/ on container start
# The wrapper will exec to the base image's original entrypoint
ENTRYPOINT ["/usr/local/bin/startup.sh"]
# Note: CMD is inherited from base image (openshell-sandbox)
