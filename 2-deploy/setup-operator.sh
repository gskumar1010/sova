#!/usr/bin/env bash
# setup-operator.sh -- Deploy OpenShell + Kata secured agent sandbox using Kubernetes Operator
#
# This is Phase 2 (namespace admin). It deploys the OpenShell gateway,
# creates the dual-protection sandbox using CRDs, and configures secrets.
#
# Prerequisites:
#   - Phase 1 complete (Kata installed)
#   - oc CLI logged in
#   - helm v3 installed
#   - OpenShell Kubernetes Operator installed (CRDs available)
#   - Container image built and pushed to REGISTRY
#   - env.sh configured (cp env.sh.example env.sh)
#
# Usage:
#   source env.sh
#   ./2-deploy/setup-operator.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight ---

info "Running preflight checks..."

command -v oc   >/dev/null || fatal "oc CLI not found"
command -v helm >/dev/null || fatal "helm not found"
oc whoami >/dev/null 2>&1 || fatal "Not logged in to OpenShift (run oc login first)"

[ -n "${REGISTRY:-}" ]       || fatal "REGISTRY not set. Source env.sh first."
[ -n "${NAMESPACE:-}" ]      || fatal "NAMESPACE not set. Source env.sh first."
[ -n "${MODEL_ENDPOINT:-}" ] || fatal "MODEL_ENDPOINT not set. Source env.sh first."
[ -n "${OPENAI_API_KEY:-}" ] || fatal "OPENAI_API_KEY not set. Source env.sh first."

info "Registry:       ${REGISTRY}"
info "Namespace:      ${NAMESPACE}"
info "Model endpoint: ${MODEL_ENDPOINT}"

# --- Check for OpenShell CRDs ---

info "Checking for OpenShell Kubernetes Operator CRDs..."
# Check for CRDs - they may use either openshell.nvidia.com or openshell.lenshq.io domain
if oc get crd openshellsandboxes.openshell.nvidia.com >/dev/null 2>&1; then
    CRD_DOMAIN="openshell.nvidia.com"
    info "OpenShell CRDs found (nvidia.com domain)"
elif oc get crd openshellsandboxes.openshell.lenshq.io >/dev/null 2>&1; then
    CRD_DOMAIN="openshell.lenshq.io"
    info "OpenShell CRDs found (lenshq.io domain)"
else
    warn "OpenShellSandbox CRD not found!"
    warn "The OpenShell Kubernetes Operator must be installed first."
    warn "See: 2-deploy/INSTALL-OPERATOR.md"
    fatal "Missing required CRDs"
fi

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
    | sed "s|REGISTRY_PLACEHOLDER|image-registry.openshift-image-registry.svc:5000/${NAMESPACE}|g" \
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

# Add required annotation for OpenShell operator to use this secret
info "Adding OpenShell provider annotation to secret..."
oc annotate secret opencode-api-keys -n "${NAMESPACE}" \
    openshell.lenshq.io/allow-provider-ref=true --overwrite

# --- 4. Parse MODEL_ENDPOINT for OpenShell policy ---

info "Parsing MODEL_ENDPOINT for OpenShell policy..."
# Parse host and port from MODEL_ENDPOINT for the OpenShell policy
_scheme=$(echo "${MODEL_ENDPOINT}" | sed -E 's|^([^:]+)://.*|\1|')
_no_scheme=$(echo "${MODEL_ENDPOINT}" | sed -E 's|^https?://||')
_hostport=$(echo "${_no_scheme}" | cut -d/ -f1)
MODEL_HOST=$(echo "${_hostport}" | cut -d: -f1)
if echo "${_hostport}" | grep -q ':'; then
    MODEL_PORT=$(echo "${_hostport}" | cut -d: -f2)
else
    # Use scheme-appropriate default port
    if [ "${_scheme}" = "https" ]; then
        MODEL_PORT="443"
    elif [ "${_scheme}" = "http" ]; then
        MODEL_PORT="80"
    else
        MODEL_PORT="8000"
    fi
fi
info "Model host: ${MODEL_HOST}, port: ${MODEL_PORT}"

# --- 5. Generate JWT signing keys ---

info "Generating JWT signing keys..."
if ! oc get secret openshell-jwt-keys -n "${NAMESPACE}" >/dev/null 2>&1; then
    JWT_DIR=$(mktemp -d)
    mkdir -p "${JWT_DIR}/jwt"

    # Generate Ed25519 key pair (required by OpenShell gateway)
    openssl genpkey -algorithm Ed25519 -out "${JWT_DIR}/jwt/signing.pem" 2>/dev/null
    openssl pkey -in "${JWT_DIR}/jwt/signing.pem" -pubout -out "${JWT_DIR}/jwt/public.pem" 2>/dev/null

    # Generate a random key ID
    echo "$(date +%s)-$(openssl rand -hex 4)" > "${JWT_DIR}/jwt/kid"

    oc create secret generic openshell-jwt-keys -n "${NAMESPACE}" \
        --from-file=signing.pem="${JWT_DIR}/jwt/signing.pem" \
        --from-file=public.pem="${JWT_DIR}/jwt/public.pem" \
        --from-file=kid="${JWT_DIR}/jwt/kid"
    rm -rf "${JWT_DIR}"
    info "JWT keys secret created."
else
    info "JWT keys secret already exists, skipping."
fi

# --- 6. OpenShell gateway ---

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

# Check for ghcr-pull secret
if ! oc get secret ghcr-pull -n "${NAMESPACE}" >/dev/null 2>&1; then
    warn "Secret 'ghcr-pull' not found in ${NAMESPACE}; the gateway image pull from ghcr.io may fail."
fi

# --- 7. Wait for gateway ---

info "Waiting for OpenShell gateway to be ready..."
oc -n "${NAMESPACE}" rollout status statefulset/openshell-kata --timeout=120s \
    || warn "Gateway not ready yet"

# --- 8. Prepare OpenCode configuration ---

info "Preparing OpenCode configuration..."
# OpenCode configuration injected into the sandbox. It is passed inline via
# OPENCODE_CONFIG_CONTENT so it does not depend on the baked image config.
OPENCODE_CFG='{"$schema":"https://opencode.ai/config.json","model":"qwen/qwen3-14b","autoupdate":false,"share":"disabled","plugin":[],"provider":{"qwen":{"npm":"@ai-sdk/openai-compatible","name":"Qwen (vLLM)","options":{"baseURL":"{env:OPENAI_BASE_URL}","apiKey":"{env:OPENAI_API_KEY}"},"models":{"qwen3-14b":{}}}}}'

# --- 9. Apply OpenShell CRDs ---

info "Applying OpenShell CRDs (Provider, Policy, Sandbox)..."

# Apply OpenShellProvider
info "Creating OpenShellProvider..."
sed -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|MODEL_ENDPOINT_PLACEHOLDER|${MODEL_ENDPOINT}|g" \
    "${SCRIPT_DIR}/openshell-provider.yaml" \
    | oc apply -f -

# Apply OpenShellPolicy
info "Creating OpenShellPolicy..."
sed -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|MODEL_HOST_PLACEHOLDER|${MODEL_HOST}|g" \
    -e "s|MODEL_PORT_PLACEHOLDER|${MODEL_PORT}|g" \
    "${SCRIPT_DIR}/openshell-policy-crd.yaml" \
    | oc apply -f -

# Apply OpenShellSandbox
info "Creating OpenShellSandbox..."
# Escape the JSON config for use in sed
OPENCODE_CFG_ESCAPED=$(echo "${OPENCODE_CFG}" | sed 's|/|\\/|g' | sed 's|"|\\"|g')
sed -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|REGISTRY_PLACEHOLDER|image-registry.openshift-image-registry.svc:5000/${NAMESPACE}|g" \
    -e "s|MODEL_ENDPOINT_PLACEHOLDER|${MODEL_ENDPOINT}|g" \
    -e "s|API_KEY_PLACEHOLDER|${OPENAI_API_KEY}|g" \
    -e "s|OPENCODE_CFG_PLACEHOLDER|${OPENCODE_CFG_ESCAPED}|g" \
    "${SCRIPT_DIR}/openshell-sandbox.yaml" \
    | oc apply -f -

# --- 10. Wait for sandbox pod ---

info "Waiting for sandbox pod to be created..."
# The operator creates a pod based on the OpenShellSandbox CRD
# Pod name format: <namespace>--<sandbox-name> or similar
SANDBOX_POD=""
for _ in $(seq 1 30); do
    SANDBOX_POD=$(oc get pods -n "${NAMESPACE}" -l app=vuln-agent,component=sandbox -o name 2>/dev/null \
        | sed 's|^pod/||' | head -1)
    if [ -z "${SANDBOX_POD}" ]; then
        # Fallback: try OpenShell naming convention
        SANDBOX_POD=$(oc get pods -n "${NAMESPACE}" -o name 2>/dev/null \
            | sed 's|^pod/||' | grep -E -- '(^|--)opencode-dual$' | head -1)
    fi
    [ -n "${SANDBOX_POD}" ] && break
    sleep 2
done

if [ -n "${SANDBOX_POD}" ]; then
    info "Found sandbox pod: ${SANDBOX_POD}"
    oc wait --for=condition=Ready "pod/${SANDBOX_POD}" \
        -n "${NAMESPACE}" --timeout=180s || warn "Pod not ready"
else
    warn "Sandbox pod not found - check OpenShellSandbox status:"
    oc get openshellsandbox -n "${NAMESPACE}" opencode-dual -o yaml 2>/dev/null || true
fi

# --- 11. Stage the vulnerability scanning tool + security analyst persona ---
# The image bakes these into /home/user/workspace, but the sandbox agent runs
# with its cwd in the PVC-backed workspace (/sandbox). Copy them so OpenCode
# finds vuln_scan.py and loads the SECURITY_ANALYST.md persona.

if [ -n "${SANDBOX_POD}" ]; then
    info "Staging vulnerability scanning tool and security analyst persona..."
    oc exec -n "${NAMESPACE}" "${SANDBOX_POD}" -- \
        sh -c 'cp -f /home/user/workspace/vuln_scan.py /home/user/workspace/SECURITY_ANALYST.md /sandbox/ 2>/dev/null && echo staged' \
        2>/dev/null || warn "Could not stage workspace files (do it manually before running the demo)"
fi

# --- Done ---

echo ""
info "========================================="
info " Phase 2: Deployment complete (Operator)"
info "========================================="
echo ""
info "Namespace:         ${NAMESPACE}"
info "Model endpoint:    ${MODEL_ENDPOINT}"
info "OpenShell gateway: $(oc get pod -n "${NAMESPACE}" -l app.kubernetes.io/name=openshell -o name 2>/dev/null || echo 'not found')"
info "Agent sandbox:     opencode-dual"
echo ""
info "CRD Status:"
oc get openshellpolicy,openshellprovider,openshellsandbox -n "${NAMESPACE}" 2>/dev/null || true
echo ""
info "Pod status:"
oc get pod -n "${NAMESPACE}" -l app=vuln-agent 2>/dev/null || oc get pod "${SANDBOX_POD}" -n "${NAMESPACE}" -o wide 2>/dev/null || true
echo ""
info "Waiting for SOVA dashboard UI..."
oc -n "${NAMESPACE}" rollout status deployment/sova-dashboard-ui --timeout=120s || warn "sova-dashboard-ui not ready"
UI_HOST=$(oc get route sova-dashboard-ui -n "${NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "${UI_HOST}" ]; then
    info "SOVA Dashboard UI: https://${UI_HOST}"
fi

echo ""
info "Next step: Phase 3 - Verify (see 3-demo/README.md)"
info ""
info "To update the policy at runtime:"
info "  oc edit openshellpolicy vuln-agent-policy -n ${NAMESPACE}"
info ""
info "To view sandbox logs:"
info "  oc logs -n ${NAMESPACE} ${SANDBOX_POD:-<sandbox-pod>} -f"
