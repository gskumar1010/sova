#!/usr/bin/env bash
# setup.sh -- Install Kata Containers infrastructure on OpenShift
#
# This is Phase 1 (cluster-admin). It installs the OpenShift Sandboxed
# Containers operator, creates the KataConfig (which triggers node
# reboots), and patches the Kata initramfs with the veth module.
#
# Prerequisites:
#   - oc CLI logged in with cluster-admin privileges
#
# Usage: ./1-infra/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight ---

info "Running preflight checks..."
command -v oc >/dev/null || fatal "oc CLI not found"
oc whoami >/dev/null 2>&1 || fatal "Not logged in to OpenShift (run oc login first)"

# --- 1. Install operator and KataConfig ---

info "Applying Kata operator and KataConfig..."
oc apply -k "${SCRIPT_DIR}"

# --- 2. Wait for operator ---

info "Waiting for Sandboxed Containers operator to be ready..."
oc wait --for=condition=Available deployment/controller-manager \
    -n openshift-sandboxed-containers-operator \
    --timeout=300s 2>/dev/null \
    || warn "Operator deployment not found or not ready yet. It may still be installing."

# --- 3. Wait for KataConfig ---

info "Waiting for KataConfig to complete (this triggers node reboots)..."
info "This may take 10-20 minutes depending on the number of worker nodes."

TIMEOUT=1200
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    READY=$(oc get kataconfig default -o jsonpath='{.status.totalNodesCount}' 2>/dev/null || echo "0")
    COMPLETED=$(oc get kataconfig default -o jsonpath='{.status.installationStatus.completed.completedNodesCount}' 2>/dev/null || echo "0")

    if [ "${READY}" != "0" ] && [ "${READY}" = "${COMPLETED}" ]; then
        info "All ${READY} worker nodes are ready with Kata."
        break
    fi

    info "  Nodes ready: ${COMPLETED}/${READY} (${ELAPSED}s elapsed)"
    sleep 30
    ELAPSED=$((ELAPSED + 30))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Timed out waiting for KataConfig. Check node status manually:"
    warn "  oc get kataconfig default -o yaml"
fi

# --- 4. Patch Kata initramfs for veth module ---

info "Patching Kata initramfs with veth kernel module..."
info "(Required for OpenShell network namespace setup)"
oc apply -f "${SCRIPT_DIR}/kata-veth-patch-job.yaml"

info "Waiting for veth patch to complete on all nodes..."
sleep 10
for pod in $(oc get pods -n openshift-sandboxed-containers-operator \
    -l app=kata-veth-patch -o name 2>/dev/null); do
    oc wait --for=condition=Ready "${pod}" \
        -n openshift-sandboxed-containers-operator \
        --timeout=120s 2>/dev/null || warn "veth patch pod not ready: ${pod}"
done

# Show patch results
for pod in $(oc get pods -n openshift-sandboxed-containers-operator \
    -l app=kata-veth-patch -o name 2>/dev/null); do
    NODE=$(oc get "${pod}" -n openshift-sandboxed-containers-operator \
        -o jsonpath='{.spec.nodeName}' 2>/dev/null)
    LOG=$(oc logs -n openshift-sandboxed-containers-operator "${pod}" 2>/dev/null | tail -2)
    info "  ${NODE}: ${LOG}"
done

# Clean up patch DaemonSet
oc delete -f "${SCRIPT_DIR}/kata-veth-patch-job.yaml" --ignore-not-found 2>/dev/null || true

# --- 5. Verify ---

info "Running Kata verification..."
bash "${SCRIPT_DIR}/verify-kata.sh"

echo ""
info "========================================="
info " Phase 1: Infrastructure complete"
info "========================================="
echo ""
info "NOTE: The veth initramfs patch does not survive node reboots."
info "      Re-run this script after cluster maintenance."
echo ""
info "Next step: Phase 2 - Deploy (see 2-deploy/README.md)"
