# Agent sandbox image for OpenShell + Kata reference architecture
#
# Based on the OpenShell community base sandbox image.
# Adds: Python 3, curl, jq, git, requests, OpenCode config, and the
# travel-agent tool + persona.
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
    && pip3 install --no-cache-dir --break-system-packages requests==2.32.3 \
    && rm -rf /var/lib/apt/lists/*

COPY images/agent-sandbox/opencode.json /home/user/.config/opencode/config.json
COPY app/agent_tools/travel_search.py /home/user/workspace/travel_search.py
COPY images/agent-sandbox/AGENTS.md /home/user/workspace/AGENTS.md

USER user
WORKDIR /home/user/workspace
