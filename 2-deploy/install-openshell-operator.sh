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

# --- 3. Check for existing gateway ---

info "Checking for existing OpenShell gateway..."
GATEWAY_SVC=$(oc get svc -n "${NAMESPACE}" -o name 2>/dev/null | grep openshell | head -1 | sed 's|service/||' || true)

if [ -n "${GATEWAY_SVC}" ]; then
    # Use existing gateway
    GATEWAY_ENDPOINT="http://${GATEWAY_SVC}.${NAMESPACE}.svc.cluster.local:8080"
    USE_BUNDLED="false"
    info "Found existing gateway: ${GATEWAY_ENDPOINT}"
else
    # Let operator deploy its own gateway
    USE_BUNDLED="true"
    GATEWAY_ENDPOINT=""
    info "No existing gateway found - operator will deploy one"
fi

# --- 4. Build chart dependencies ---

info "Building Helm chart dependencies..."
cd deploy/charts/openshell-operator

# The chart has a dependency on the OpenShell gateway Helm chart
# Even though we're using gateway.bundled=false, we still need to download it
info "Downloading chart dependencies from OCI registry..."
helm dependency build

cd "${TEMP_DIR}/openshell-operator"

# --- 5. Create namespace and SCCs ---

# Create namespace first
oc create namespace "${OPERATOR_NS}" 2>/dev/null || true

info "Granting privileged SCC to operator service accounts..."
# The operator requires privileged SCC due to seccomp annotations and specific UIDs
# Grant to all service accounts that will be created by the operator Helm chart
for sa in default openshell-operator openshell-issuer openshell-gateway openshell-operator-issuer-mint openshell-gateway-certgen; do
    oc adm policy add-scc-to-user privileged \
        "system:serviceaccount:${OPERATOR_NS}:${sa}" 2>/dev/null || warn "SCC binding for ${sa} may already exist"
done

# --- 6. Install operator with external gateway ---

if [ "${USE_BUNDLED}" = "true" ]; then
    info "Installing operator with bundled gateway..."
    helm upgrade --install openshell-operator deploy/charts/openshell-operator \
        --namespace "${OPERATOR_NS}" \
        --create-namespace \
        --set gateway.bundled=true \
        --set auth.mode=bundledOidc \
        --timeout 10m \
        --wait
else
    info "Installing operator to use existing gateway..."
    helm upgrade --install openshell-operator deploy/charts/openshell-operator \
        --namespace "${OPERATOR_NS}" \
        --create-namespace \
        --set gateway.bundled=false \
        --set gateway.endpoint="${GATEWAY_ENDPOINT}" \
        --set gateway.namespace="${NAMESPACE}" \
        --set auth.mode=none \
        --timeout 10m \
        --wait
fi

# --- 7. Verify installation ---

info "Verifying CRDs..."
sleep 5

# Check for CRDs with either domain (nvidia.com or lenshq.io)
CRD_COUNT=$(oc get crd | grep -c "openshell\." || true)
if [ "${CRD_COUNT}" -eq 0 ]; then
    warn "OpenShell CRDs not found. Checking installation..."
    oc get pods -n "${OPERATOR_NS}"
    fatal "CRD installation failed"
fi

info "Found ${CRD_COUNT} OpenShell CRDs:"
oc get crd | grep "openshell\."

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
if [ "${USE_BUNDLED}" = "true" ]; then
    info "Gateway mode:       Bundled (deployed by operator)"
else
    info "Gateway endpoint:   ${GATEWAY_ENDPOINT}"
fi
echo ""
info "CRDs installed:"
oc get crd | grep "openshell\." || true
echo ""
info "Operator pods:"
oc get pods -n "${OPERATOR_NS}"
echo ""
if [ "${USE_BUNDLED}" = "true" ]; then
    info "Next step: Run ./2-deploy/setup-operator.sh to deploy your application and agent sandbox"
else
    info "Next step: Run ./2-deploy/setup-operator.sh to deploy your agent"
fi
