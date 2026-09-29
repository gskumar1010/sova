#!/usr/bin/env bash
# build-images.sh - Build and push container images for SOVA
#
# This script builds all container images needed for the SOVA project:
#   - Agent sandbox (OpenShell + Kata security)
#   - Vulnerability orchestrator API
#   - SOVA dashboard UI
#
# Usage:
#   source env.sh
#   ./2-deploy/build-images.sh [OPTIONS]
#
# Options:
#   --sandbox-only    Build only the agent sandbox image
#   --apps-only       Build only the application images (API + UI)
#   --skip-push       Build but don't push to registry

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# --- Parse arguments ---

BUILD_SANDBOX=1
BUILD_APPS=1
SKIP_PUSH=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --sandbox-only)
            BUILD_APPS=0
            shift
            ;;
        --apps-only)
            BUILD_SANDBOX=0
            shift
            ;;
        --skip-push)
            SKIP_PUSH=1
            shift
            ;;
        *)
            fatal "Unknown option: $1"
            ;;
    esac
done

# --- Preflight checks ---

info "Running preflight checks..."

command -v podman >/dev/null || fatal "podman not found"
[ -n "${REGISTRY:-}" ]  || fatal "REGISTRY not set. Source env.sh first."
[ -n "${NAMESPACE:-}" ] || fatal "NAMESPACE not set. Source env.sh first."

info "Registry:  ${REGISTRY}"
info "Namespace: ${NAMESPACE}"

# --- Build and push images ---

if [ "${BUILD_SANDBOX}" = "1" ]; then
    info "Building agent sandbox image..."
    podman build --platform=linux/amd64 -f images/agent-sandbox/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest" .

    if [ "${SKIP_PUSH}" = "0" ]; then
        info "Pushing agent sandbox image..."
        podman push "${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest"
    else
        warn "Skipping push for agent sandbox image"
    fi
fi

if [ "${BUILD_APPS}" = "1" ]; then
    info "Building vulnerability orchestrator API image..."
    podman build --platform=linux/amd64 -f images/vuln-orchestrator/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest" .

    if [ "${SKIP_PUSH}" = "0" ]; then
        info "Pushing vulnerability orchestrator API image..."
        podman push "${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest"
    else
        warn "Skipping push for vulnerability orchestrator API image"
    fi

    info "Building SOVA dashboard UI image..."
    podman build --platform=linux/amd64 -f images/vuln-ui/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest" .

    if [ "${SKIP_PUSH}" = "0" ]; then
        info "Pushing SOVA dashboard UI image..."
        podman push "${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest"
    else
        warn "Skipping push for SOVA dashboard UI image"
    fi
fi

# --- Done ---

echo ""
info "========================================="
info " Image Build Complete"
info "========================================="
echo ""

if [ "${BUILD_SANDBOX}" = "1" ]; then
    info "Agent sandbox:   ${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest"
fi

if [ "${BUILD_APPS}" = "1" ]; then
    info "Orchestrator API: ${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest"
    info "Dashboard UI:     ${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest"
fi

echo ""

if [ "${SKIP_PUSH}" = "1" ]; then
    info "Images built locally but NOT pushed to registry"
    info "Run without --skip-push to push images"
else
    info "Images pushed to registry successfully"
fi
