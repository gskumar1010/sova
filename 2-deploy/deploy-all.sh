#!/usr/bin/env bash
# deploy-all.sh - Complete SOVA deployment with OpenShell Operator
#
# This script runs the full deployment in the correct order:
# 1. Deploy gateway, application, and CRDs (setup-operator.sh)
# 2. Wait for gateway to be ready
# 3. Install operator to manage the CRDs (install-openshell-operator.sh)
#
# Prerequisites:
#   - Phase 1 complete (Kata installed)
#   - oc CLI logged in with cluster admin access
#   - helm v3 installed
#   - Container images built and pushed
#   - env.sh configured
#
# Usage:
#   source env.sh
#   ./2-deploy/deploy-all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight ---

info "Running preflight checks..."

[ -n "${NAMESPACE:-}" ] || fatal "NAMESPACE not set. Source env.sh first."
[ -n "${REGISTRY:-}" ] || fatal "REGISTRY not set. Source env.sh first."
[ -n "${MODEL_ENDPOINT:-}" ] || fatal "MODEL_ENDPOINT not set. Source env.sh first."
[ -n "${OPENAI_API_KEY:-}" ] || fatal "OPENAI_API_KEY not set. Source env.sh first."

command -v oc   >/dev/null || fatal "oc CLI not found"
command -v helm >/dev/null || fatal "helm not found"
oc whoami >/dev/null 2>&1 || fatal "Not logged in to OpenShift (run oc login first)"

info "Environment:"
info "  Namespace:      ${NAMESPACE}"
info "  Registry:       ${REGISTRY}"
info "  Model endpoint: ${MODEL_ENDPOINT}"

# --- Phase 1: Deploy Gateway and Application ---

echo ""
info "========================================="
info " Phase 1: Deploying Gateway and App"
info "========================================="
echo ""

info "Running setup-operator.sh..."
"${SCRIPT_DIR}/setup-operator.sh"

# --- Phase 2: Wait for Gateway ---

echo ""
info "========================================="
info " Phase 2: Waiting for Gateway Ready"
info "========================================="
echo ""

info "Waiting for gateway pod to be fully ready..."
MAX_WAIT=180
ELAPSED=0
GATEWAY_READY=false

while [ ${ELAPSED} -lt ${MAX_WAIT} ]; do
    if oc wait --for=condition=Ready pod -l app.kubernetes.io/name=openshell \
        -n "${NAMESPACE}" --timeout=10s >/dev/null 2>&1; then
        GATEWAY_READY=true
        break
    fi
    ELAPSED=$((ELAPSED + 10))
    info "Still waiting... (${ELAPSED}s/${MAX_WAIT}s)"
done

if [ "${GATEWAY_READY}" != "true" ]; then
    warn "Gateway not ready after ${MAX_WAIT}s"
    info "Checking gateway pod status:"
    oc get pods -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell
    info "Checking gateway logs:"
    oc logs -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell --tail=20 || true
    fatal "Gateway failed to become ready"
fi

info "Gateway is ready!"

# Verify gateway is responding
info "Testing gateway connectivity..."
GATEWAY_POD=$(oc get pod -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell -o name | head -1)
if oc exec -n "${NAMESPACE}" "${GATEWAY_POD}" -- curl -s http://localhost:8080/health >/dev/null 2>&1; then
    info "Gateway health check passed!"
else
    warn "Gateway health check failed, but continuing..."
fi

# --- Phase 3: Install Operator ---

echo ""
info "========================================="
info " Phase 3: Installing Operator"
info "========================================="
echo ""

info "Running install-openshell-operator.sh..."
"${SCRIPT_DIR}/install-openshell-operator.sh"

# --- Phase 4: Verify Complete Deployment ---

echo ""
info "========================================="
info " Phase 4: Verification"
info "========================================="
echo ""

info "Waiting for operator to become ready..."
if oc wait --for=condition=Ready pod \
    -n openshell-operator-system \
    -l app.kubernetes.io/name=openshell-operator \
    --timeout=120s 2>/dev/null; then
    info "Operator is ready!"
else
    warn "Operator may not be fully ready yet"
fi

echo ""
info "Checking OpenShell resources..."
echo ""

info "Gateway:"
oc get pods -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell

echo ""
info "Operator:"
oc get pods -n openshell-operator-system

echo ""
info "CRDs:"
oc get openshellpolicy,openshellprovider,openshellsandbox -n "${NAMESPACE}"

echo ""
info "Sandbox pod:"
SANDBOX_POD=$(oc get pods -n "${NAMESPACE}" -o name 2>/dev/null \
    | sed 's|^pod/||' | grep -E -- '(^|--)opencode-dual$' | head -1 || true)

if [ -n "${SANDBOX_POD}" ]; then
    oc get pod "${SANDBOX_POD}" -n "${NAMESPACE}"

    # Wait for sandbox to be ready
    info "Waiting for sandbox pod to be ready..."
    if oc wait --for=condition=Ready "pod/${SANDBOX_POD}" \
        -n "${NAMESPACE}" --timeout=180s 2>/dev/null; then
        info "Sandbox pod is ready!"
    else
        warn "Sandbox pod not ready yet - check status with:"
        warn "  oc get pod ${SANDBOX_POD} -n ${NAMESPACE}"
        warn "  oc describe pod ${SANDBOX_POD} -n ${NAMESPACE}"
    fi
else
    warn "Sandbox pod not found - it may still be creating"
    info "Check sandbox status with:"
    info "  oc get openshellsandbox opencode-dual -n ${NAMESPACE}"
fi

echo ""
info "Application:"
oc get pods -n "${NAMESPACE}" -l app.kubernetes.io/part-of=openshell-kata

# --- Done ---

echo ""
info "========================================="
info " Deployment Complete!"
info "========================================="
echo ""

info "Dashboard UI:"
UI_ROUTE=$(oc get route sova-dashboard-ui -n "${NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "${UI_ROUTE}" ]; then
    info "  https://${UI_ROUTE}"
else
    warn "  Route not found"
fi

echo ""
info "Next steps:"
info "  1. Access the SOVA dashboard at the URL above"
info "  2. Test vulnerability scanning with a repository"
info "  3. Verify policy enforcement is working"
echo ""
info "Troubleshooting commands:"
info "  # Check all resources"
info "  oc get all -n ${NAMESPACE}"
info ""
info "  # Check operator logs"
info "  oc logs -n openshell-operator-system deployment/openshell-operator -f"
info ""
info "  # Check gateway logs"
info "  oc logs -n ${NAMESPACE} -l app.kubernetes.io/name=openshell -f"
info ""
info "  # Check sandbox status"
info "  oc get openshellsandbox opencode-dual -n ${NAMESPACE} -o yaml"
echo ""
