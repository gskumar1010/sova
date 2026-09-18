#!/usr/bin/env bash
# install-openshell-operator.sh - Install OpenShell Kubernetes Operator
#
# This script installs the OpenShell Kubernetes Operator CRDs and controller
# to work with your existing OpenShell gateway.
#
# Usage:
#   source env.sh
#   ./2-deploy/install-openshell-operator.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

[ -n "${NAMESPACE:-}" ] || fatal "NAMESPACE not set. Source env.sh first."

OPERATOR_NS="openshell-operator-system"
OPERATOR_REPO="https://github.com/lensapp/openshell-k8s-operator.git"
TEMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

info "Installing OpenShell Kubernetes Operator..."

# --- 1. Clone the operator repository ---

info "Cloning operator repository..."
git clone --depth 1 "${OPERATOR_REPO}" "${TEMP_DIR}/openshell-operator"
cd "${TEMP_DIR}/openshell-operator"

# --- 2. Check for Helm chart ---

if [ ! -d "deploy/charts/openshell-operator" ]; then
    fatal "Helm chart not found in repository. The operator structure may have changed."
fi

# --- 3. Get gateway endpoint ---

info "Detecting existing OpenShell gateway..."
GATEWAY_SVC=$(oc get svc -n "${NAMESPACE}" -o name | grep openshell | head -1 | sed 's|service/||')
if [ -z "${GATEWAY_SVC}" ]; then
    fatal "OpenShell gateway service not found in namespace ${NAMESPACE}"
fi

GATEWAY_ENDPOINT="http://${GATEWAY_SVC}.${NAMESPACE}.svc.cluster.local:8080"
info "Gateway endpoint: ${GATEWAY_ENDPOINT}"

# --- 4. Build chart dependencies ---

info "Building Helm chart dependencies..."
cd deploy/charts/openshell-operator

# The chart has a dependency on the OpenShell gateway Helm chart
# Even though we're using gateway.bundled=false, we still need to download it
info "Downloading chart dependencies from OCI registry..."
helm dependency build

cd "${TEMP_DIR}/openshell-operator"

# --- 5. Create SCC for operator ---

info "Creating SCC for operator namespace..."
oc apply -f "${SCRIPT_DIR}/openshell-operator-scc.yaml" 2>/dev/null || warn "SCC may already exist"

# Create namespace first to get the service account
oc create namespace "${OPERATOR_NS}" 2>/dev/null || true

# Grant SCC to default service account (will be created by Helm)
oc adm policy add-scc-to-user openshell-operator-scc \
    "system:serviceaccount:${OPERATOR_NS}:default" 2>/dev/null || warn "SCC binding may already exist"

# --- 6. Install operator with external gateway ---

info "Installing operator to use existing gateway..."

# Use upgrade --install to handle both new installs and upgrades
# Disable auth mode since we're using external gateway
helm upgrade --install openshell-operator deploy/charts/openshell-operator \
    --namespace "${OPERATOR_NS}" \
    --create-namespace \
    --set gateway.bundled=false \
    --set gateway.endpoint="${GATEWAY_ENDPOINT}" \
    --set gateway.namespace="${NAMESPACE}" \
    --set auth.mode=none \
    --timeout 10m \
    --wait

# --- 7. Verify installation ---

info "Verifying CRDs..."
sleep 5

CRD_COUNT=$(oc get crd | grep -c "openshell.nvidia.com" || true)
if [ "${CRD_COUNT}" -eq 0 ]; then
    warn "OpenShell CRDs not found. Checking installation..."
    oc get pods -n "${OPERATOR_NS}"
    fatal "CRD installation failed"
fi

info "Found ${CRD_COUNT} OpenShell CRDs:"
oc get crd | grep "openshell.nvidia.com"

# --- 8. Wait for operator pod ---

info "Waiting for operator pod to be ready..."
oc wait --for=condition=Ready pod \
    -n "${OPERATOR_NS}" \
    -l app.kubernetes.io/name=openshell-operator \
    --timeout=120s || warn "Operator pod not ready yet"

# --- Done ---

echo ""
info "========================================="
info " OpenShell Operator Installation Complete"
info "========================================="
echo ""
info "Operator namespace: ${OPERATOR_NS}"
info "Gateway endpoint:   ${GATEWAY_ENDPOINT}"
echo ""
info "CRDs installed:"
oc get crd | grep "openshell.nvidia.com" || true
echo ""
info "Operator pods:"
oc get pods -n "${OPERATOR_NS}"
echo ""
info "Next step: Run ./2-deploy/setup-operator.sh to deploy your agent"
