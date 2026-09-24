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

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        curl \
        jq \
        git \
        ripgrep \
    && pip3 install --no-cache-dir --break-system-packages \
        requests==2.32.3 \
        gitpython==3.1.43 \
    && rm -rf /var/lib/apt/lists/*

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
