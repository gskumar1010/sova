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

# --- Build and push app images ---

if [ "${SKIP_BUILD:-0}" = "1" ]; then
    info "SKIP_BUILD=1 - skipping image build/push (assuming images already pushed)"
else
    info "Building and pushing SOVA app images..."
    podman build --platform=linux/amd64 -f images/vuln-orchestrator/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest" .
    podman push "${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest"
    podman build --platform=linux/amd64 -f images/vuln-ui/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest" .
    podman push "${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest"
fi

# --- 1. Namespace and SCC ---

info "Creating namespace, SCC, vulnerability orchestrator API, and SOVA dashboard UI..."
oc kustomize "${SCRIPT_DIR}" \
    | sed "s|REGISTRY_PLACEHOLDER|${REGISTRY}|g" \
    | oc apply -f -

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

info "Installing OpenShell gateway via Helm (latest chart)..."
if helm status openshell -n "${NAMESPACE}" >/dev/null 2>&1; then
    info "OpenShell already installed, upgrading..."
    helm upgrade openshell oci://ghcr.io/nvidia/openshell/helm-chart \
        -n "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/openshell-helm-values.yaml" \
        --set server.sandboxImage="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/openshell-kata-agent-sandbox:latest"
else
    helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
        -n "${NAMESPACE}" \
        -f "${SCRIPT_DIR}/openshell-helm-values.yaml" \
        --set server.sandboxImage="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/openshell-kata-agent-sandbox:latest"
fi

# The ghcr-pull secret (referenced by openshell-helm-values.yaml for both the
# gateway pod and sandbox pods) must exist in the namespace before the gateway
# starts pulling. setup expects it to be created out of band, e.g.:
#   oc -n "${NAMESPACE}" create secret docker-registry ghcr-pull \
#     --docker-server=ghcr.io --docker-username=<user> \
#     --docker-password="$(gh auth token)"
if ! oc get secret ghcr-pull -n "${NAMESPACE}" >/dev/null 2>&1; then
    warn "Secret 'ghcr-pull' not found in ${NAMESPACE}; the gateway image pull from ghcr.io may fail."
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
oc -n "${NAMESPACE}" rollout status statefulset/openshell-kata --timeout=120s \
    || warn "Gateway not ready yet"

# --- 8. Port-forward to gateway ---

info "Starting port-forward to OpenShell gateway..."
pkill -f "port-forward.*svc/openshell-kata.*18080" 2>/dev/null || true
sleep 1
oc port-forward -n "${NAMESPACE}" svc/openshell-kata 18080:8080 > /tmp/openshell-pf.log 2>&1 &
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

# OpenCode configuration injected into the sandbox. It is passed inline via
# OPENCODE_CONFIG_CONTENT so it does not depend on the baked image config.
# IMPORTANT: use a custom provider with npm "@ai-sdk/openai-compatible" (bundled
# in OpenCode, no network fetch). The built-in "openai" provider uses the OpenAI
# *Responses* API (.responses()), which breaks tool-calling for vLLM-served
# models like gemma (the model emits the tool call as plain text and never runs
# the tool). "@ai-sdk/openai-compatible" uses the chat/completions API, which
# matches vLLM's --tool-call-parser and makes real tool calls work.
# autoupdate/share/plugin are disabled so OpenCode does not phone home to
# opencode.ai / registry.npmjs.org (those are correctly blocked by the egress
# policy anyway; disabling them just avoids the noise and startup latency).
OPENCODE_CFG='{"$schema":"https://opencode.ai/config.json","model":"gemma/gemma4-31b","autoupdate":false,"share":"disabled","plugin":[],"provider":{"gemma":{"npm":"@ai-sdk/openai-compatible","name":"gemma (vLLM)","options":{"baseURL":"{env:OPENAI_BASE_URL}","apiKey":"{env:OPENAI_API_KEY}"},"models":{"gemma4-31b":{}}}}}'

# --env sets non-secret env vars in the sandbox. The model endpoint has no auth,
# so OPENAI_API_KEY is a dummy. The OPENCODE_DISABLE_* flags keep OpenCode fully
# offline (no models.dev / npm / opencode.ai fetches), which is required behind
# the deny-all egress policy.
openshell sandbox create \
    --name opencode-dual \
    --policy "${POLICY_FILE}" \
    --driver-config-json '{"kubernetes":{"pod":{"runtime_class_name":"kata"}}}' \
    --env OPENAI_BASE_URL="${MODEL_ENDPOINT}/v1" \
    --env OPENAI_API_KEY="${OPENAI_API_KEY}" \
    --env OPENCODE_DISABLE_MODELS_FETCH=1 \
    --env OPENCODE_DISABLE_AUTOUPDATE=1 \
    --env OPENCODE_PURE=1 \
    --env OPENCODE_DISABLE_LSP_DOWNLOAD=1 \
    --env OPENCODE_DISABLE_AUTOCOMPACT=1 \
    --env OPENCODE_DB=:memory: \
    --env OPENCODE_CONFIG_CONTENT="${OPENCODE_CFG}" \
    --no-tty \
    -- sleep infinity &
_SANDBOX_PID=$!
sleep 5
kill "${_SANDBOX_PID}" 2>/dev/null || true
wait "${_SANDBOX_PID}" 2>/dev/null || true

rm -f "${POLICY_FILE}"

# --- 10. Wait for pod ---

info "Waiting for agent pod to be ready..."
# OpenShell prefixes the sandbox pod name (e.g. default--opencode-dual).
SANDBOX_POD=""
for _ in $(seq 1 30); do
    SANDBOX_POD=$(oc get pods -n "${NAMESPACE}" -o name 2>/dev/null \
        | sed 's|^pod/||' | grep -E -- '(^|--)opencode-dual$' | head -1)
    [ -n "${SANDBOX_POD}" ] && break
    sleep 2
done
if [ -n "${SANDBOX_POD}" ]; then
    oc wait --for=condition=Ready "pod/${SANDBOX_POD}" \
        -n "${NAMESPACE}" --timeout=180s || warn "Pod not ready"
else
    warn "Sandbox pod not found"
fi

# --- 10b. Stage the vulnerability scanning tool + security analyst persona ---
# The image bakes these into /home/user/workspace, but the sandbox agent runs
# with its cwd in the PVC-backed workspace (/sandbox). Copy them so OpenCode
# finds vuln_scan.py and loads the SECURITY_ANALYST.md persona.
info "Staging vulnerability scanning tool and security analyst persona..."
openshell sandbox exec -n opencode-dual --no-tty --timeout 60 -- \
    sh -c 'cp -f /home/user/workspace/vuln_scan.py /home/user/workspace/SECURITY_ANALYST.md /sandbox/ 2>/dev/null && echo staged' \
    2>/dev/null || warn "Could not stage workspace files (do it manually before running the demo)"

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
info "Waiting for SOVA dashboard UI..."
oc -n "${NAMESPACE}" rollout status deployment/sova-dashboard-ui --timeout=120s || warn "sova-dashboard-ui not ready"
UI_HOST=$(oc get route sova-dashboard-ui -n "${NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "${UI_HOST}" ]; then
    info "SOVA Dashboard UI: https://${UI_HOST}"
fi

echo ""
info "Next step: Phase 3 - Verify (see 3-demo/README.md)"
