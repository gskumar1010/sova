# Agent sandbox image for OpenShell + Kata reference architecture
#
# Based on the OpenShell community base sandbox image.
# Adds: Python 3, curl, jq, git, and OpenCode configuration.
#
# Build:
#   docker build -f images/agent-sandbox/Dockerfile \
#     -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .

FROM ghcr.io/nvidia/openshell-community/sandboxes/base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        curl \
        jq \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY images/agent-sandbox/opencode.json /home/user/.config/opencode/config.json

USER user
WORKDIR /home/user/workspace
