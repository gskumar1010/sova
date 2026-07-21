#!/usr/bin/env bash
# setup.sh -- Deploy the OpenShell + Kata secured agent sandbox
#
# This is Phase 2 (namespace admin). It deploys the OpenShell gateway,
# creates the dual-protection sandbox pod, and configures secrets.
#
# Prerequisites:
#   - Phase 1 complete (Kata installed)
#   - oc CLI logged in
#   - helm v3 installed
#   - openshell CLI installed
#   - Container image built and pushed to REGISTRY
#   - env.sh configured (cp env.sh.example env.sh)
#
# Usage:
#   source env.sh
#   ./2-deploy/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

PF_PID=""
cleanup() {
    if [ -n "${PF_PID}" ] && kill -0 "${PF_PID}" 2>/dev/null; then
        info "Stopping port-forward (PID ${PF_PID})..."
        kill "${PF_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# --- Preflight ---

info "Running preflight checks..."

command -v oc        >/dev/null || fatal "oc CLI not found"
command -v helm      >/dev/null || fatal "helm not found"
command -v openshell >/dev/null || warn "openshell CLI not found - sandbox creation will fail"
oc whoami >/dev/null 2>&1      || fatal "Not logged in to OpenShift (run oc login first)"

[ -n "${REGISTRY:-}" ]       || fatal "REGISTRY not set. Source env.sh first."
[ -n "${NAMESPACE:-}" ]      || fatal "NAMESPACE not set. Source env.sh first."
[ -n "${MODEL_ENDPOINT:-}" ] || fatal "MODEL_ENDPOINT not set. Source env.sh first."
[ -n "${OPENAI_API_KEY:-}" ] || fatal "OPENAI_API_KEY not set. Source env.sh first."

info "Registry:       ${REGISTRY}"
info "Namespace:      ${NAMESPACE}"
info "Model endpoint: ${MODEL_ENDPOINT}"

# --- 1. Namespace and SCC ---

info "Creating namespace and SCC..."
oc apply -k "${SCRIPT_DIR}"

# --- 2. SCC binding ---

info "Granting openshell-kata SCC to service accounts..."
oc patch scc openshell-kata \
    --type=json \
    -p="[
      {\"op\":\"add\",\"path\":\"/users/-\",\"value\":\"system:serviceaccount:${NAMESPACE}:openshell\"},
      {\"op\":\"add\",\"path\":\"/users/-\",\"value\":\"system:serviceaccount:${NAMESPACE}:openshell-sandbox\"}
    ]" 2>/dev/null || warn "SCC patch failed - users may already be present"

# --- 3. API key secret ---

info "Creating API key secret..."
if ! oc get secret opencode-api-keys -n "${NAMESPACE}" >/dev/null 2>&1; then
    oc create secret generic opencode-api-keys -n "${NAMESPACE}" \
        --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
        --from-literal=OPENAI_BASE_URL="${MODEL_ENDPOINT}/v1"
    info "Created opencode-api-keys secret."
else
    info "Secret opencode-api-keys already exists, skipping."
fi

# --- 4. Parse MODEL_ENDPOINT for OpenShell policy ---

info "Parsing MODEL_ENDPOINT for OpenShell policy..."
# Parse host and port from MODEL_ENDPOINT for the OpenShell policy
_no_scheme=$(echo "${MODEL_ENDPOINT}" | sed -E 's|^https?://||')
_hostport=$(echo "${_no_scheme}" | cut -d/ -f1)
MODEL_HOST=$(echo "${_hostport}" | cut -d: -f1)
if echo "${_hostport}" | grep -q ':'; then
    MODEL_PORT=$(echo "${_hostport}" | cut -d: -f2)
else
    MODEL_PORT="8000"
fi

# --- 5. OpenShell gateway ---

info "Installing OpenShell gateway via Helm..."
if helm status openshell -n "${NAMESPACE}" >/dev/null 2>&1; then
    info "OpenShell already installed, upgrading..."
    helm upgrade openshell oci://ghcr.io/nvidia/openshell/helm-chart \
        -n "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/openshell-helm-values.yaml" \
        --set server.sandboxImage="${REGISTRY}/openshell-kata-agent-sandbox:latest"
else
    helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
        -n "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/openshell-helm-values.yaml" \
        --set server.sandboxImage="${REGISTRY}/openshell-kata-agent-sandbox:latest"
fi

# --- 6. JWT signing keys ---

info "Generating JWT signing keys..."
if ! oc get secret openshell-jwt-keys -n "${NAMESPACE}" >/dev/null 2>&1; then
    JWT_DIR=$(mktemp -d)
    openshell-gateway generate-certs --output-dir "${JWT_DIR}" \
        || fatal "Failed to generate JWT keys. Is openshell-gateway installed?"
    oc create secret generic openshell-jwt-keys -n "${NAMESPACE}" \
        --from-file=signing.pem="${JWT_DIR}/jwt/signing.pem" \
        --from-file=public.pem="${JWT_DIR}/jwt/public.pem" \
        --from-file=kid="${JWT_DIR}/jwt/kid"
    rm -rf "${JWT_DIR}"
    info "JWT keys secret created."
else
    info "JWT keys secret already exists, skipping."
fi

# --- 7. Wait for gateway ---

info "Waiting for OpenShell gateway to be ready..."
oc -n "${NAMESPACE}" rollout status statefulset/openshell --timeout=120s \
    || warn "Gateway not ready yet"

# --- 8. Port-forward to gateway ---

info "Starting port-forward to OpenShell gateway..."
pkill -f "port-forward.*svc/openshell.*18080" 2>/dev/null || true
sleep 1
oc port-forward -n "${NAMESPACE}" svc/openshell 18080:8080 > /tmp/openshell-pf.log 2>&1 &
PF_PID=$!
sleep 4

if ! kill -0 "${PF_PID}" 2>/dev/null; then
    fatal "Port-forward failed to start. Check /tmp/openshell-pf.log"
fi
info "Port-forward running (PID ${PF_PID})"

# Register gateway
CURRENT_GW=$(openshell gateway list 2>/dev/null | grep '^\*' | awk '{print $3}' || true)
if [ "${CURRENT_GW}" != "http://127.0.0.1:18080" ]; then
    info "Registering gateway at http://127.0.0.1:18080..."
    openshell gateway remove openshell-kata 2>/dev/null || true
    openshell gateway add http://127.0.0.1:18080 --name openshell-kata
fi

# --- 9. Create sandbox with OpenShell + Kata ---

info "Creating dual-protection sandbox (OpenShell + Kata)..."

# Generate policy with actual model endpoint
POLICY_FILE=$(mktemp)
sed -e "s|MODEL_ENDPOINT_HOST|${MODEL_HOST}|g" \
    -e "s|MODEL_ENDPOINT_PORT|${MODEL_PORT}|g" \
    "${SCRIPT_DIR}/openshell-policy.yaml" > "${POLICY_FILE}"

openshell sandbox create \
    --name opencode-dual \
    --policy "${POLICY_FILE}" \
    --driver-config-json '{"kubernetes":{"pod":{"runtime_class_name":"kata"}}}' \
    --no-tty \
    -- sleep infinity &
_SANDBOX_PID=$!
sleep 5
kill "${_SANDBOX_PID}" 2>/dev/null || true
wait "${_SANDBOX_PID}" 2>/dev/null || true

rm -f "${POLICY_FILE}"

# --- 10. Wait for pod ---

info "Waiting for agent pod to be ready..."
oc wait --for=condition=Ready "pod/opencode-dual" \
    -n "${NAMESPACE}" --timeout=180s || warn "Pod not ready"

# --- Done ---

echo ""
info "========================================="
info " Phase 2: Deployment complete"
info "========================================="
echo ""
info "Namespace:         ${NAMESPACE}"
info "Model endpoint:    ${MODEL_ENDPOINT}"
info "OpenShell gateway: $(oc get pod -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell -o name 2>/dev/null || echo 'not found')"
info "Agent pod:         opencode-dual"
echo ""
info "Pod status:"
oc get pod opencode-dual -n "${NAMESPACE}" -o wide 2>/dev/null || true
echo ""
info "OpenShell sandbox:"
openshell sandbox list 2>/dev/null || true
echo ""
info "Next step: Phase 3 - Verify (see 3-demo/README.md)"
