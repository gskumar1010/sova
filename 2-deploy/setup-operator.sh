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
# Note: You can also use ./2-deploy/build-images.sh for standalone image builds

if [ "${SKIP_BUILD:-0}" = "1" ]; then
    info "SKIP_BUILD=1 - skipping image build/push (assuming images already pushed)"
else
    info "Building and pushing agent sandbox image..."
    podman build --platform=linux/amd64 -f images/agent-sandbox/Dockerfile \
        -t "${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest" .
    podman push "${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest"

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

# --- 5. Verify gateway is running ---

info "Verifying OpenShell gateway is running..."
# Gateway should have been deployed by install-openshell-operator.sh
if ! helm status openshell -n "${NAMESPACE}" >/dev/null 2>&1; then
    fatal "OpenShell gateway not found. Run ./2-deploy/install-openshell-operator.sh first."
fi

# Update gateway with sandbox image
info "Updating gateway with custom sandbox image..."
helm upgrade openshell oci://ghcr.io/nvidia/openshell/helm-chart \
    -n "${NAMESPACE}" \
    -f "${SCRIPT_DIR}/openshell-helm-values.yaml" \
    --set server.sandboxImage="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/openshell-kata-agent-sandbox:latest" \
    --reuse-values

# Wait for gateway
info "Waiting for OpenShell gateway to be ready..."
oc -n "${NAMESPACE}" rollout status statefulset/openshell-kata --timeout=120s \
    || warn "Gateway not ready yet"

# Link image pull secrets to sandbox service account
info "Configuring image pull secrets for sandbox service account..."
# The service account already has internal registry dockercfg (auto-generated)
# We need to also add ghcr-pull for supervisor init-container
if oc get secret ghcr-pull -n "${NAMESPACE}" >/dev/null 2>&1; then
    # Link ghcr-pull if not already linked
    if ! oc get sa openshell-sandbox -n "${NAMESPACE}" -o yaml | grep -q "ghcr-pull"; then
        oc secrets link openshell-sandbox ghcr-pull --for=pull -n "${NAMESPACE}"
        info "✓ Linked ghcr-pull secret to openshell-sandbox service account"
    else
        info "✓ ghcr-pull already linked to openshell-sandbox service account"
    fi
else
    warn "ghcr-pull secret not found - supervisor init-container pull may fail"
fi

# --- 6. Skip NetworkPolicy management ---

# IMPORTANT: OpenShell manages the NetworkPolicy (openshell-sandbox-workloads) and detects
# any modifications as tampering, suspending the sandbox. We cannot create, modify, or delete
# it without triggering this security check. Instead, we rely entirely on OpenShell's policy
# enforcement via the OpenShellPolicy CRD which allows specific endpoints (model, API, git).
# The NetworkPolicy will block general egress, but the OpenShell broker proxies allowed traffic.

info "Skipping NetworkPolicy management (using OpenShellPolicy CRD for endpoint allow-list)"

# --- 7. Prepare OpenCode configuration ---

info "Preparing OpenCode configuration..."
# Create a ConfigMap with the OpenCode configuration to avoid sed escaping issues
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: opencode-config
  namespace: ${NAMESPACE}
data:
  config.json: |
    {
      "\$schema": "https://opencode.ai/config.json",
      "model": "nemotron/nemotron-30b-vulkan",
      "autoupdate": false,
      "share": "disabled",
      "plugin": [],
      "provider": {
        "nemotron": {
          "npm": "@ai-sdk/openai-compatible",
          "name": "Nemotron (vLLM)",
          "options": {
            "baseURL": "{env:OPENAI_BASE_URL}",
            "apiKey": "{env:OPENAI_API_KEY}"
          },
          "models": {
            "nemotron-30b-vulkan": {}
          }
        }
      }
    }
EOF

# --- 8. Get vuln-orchestrator-api ClusterIP for sandbox DNS workaround ---

info "Getting vuln-orchestrator-api ClusterIP..."
VULN_API_IP=$(oc get service vuln-orchestrator-api -n "${NAMESPACE}" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "vuln-orchestrator-api")
if [ -z "${VULN_API_IP}" ] || [ "${VULN_API_IP}" = "vuln-orchestrator-api" ]; then
    warn "Could not get ClusterIP for vuln-orchestrator-api, using hostname"
    VULN_API_URL="http://vuln-orchestrator-api:8080"
else
    VULN_API_URL="http://${VULN_API_IP}:8080"
    info "Vuln API URL: ${VULN_API_URL}"
fi

# --- 9. Apply OpenShell CRDs ---

info "Applying OpenShell CRDs (Policy, Sandbox)..."

# Note: Provider is no longer needed - credentials are injected directly via environment variables

# Apply OpenShellPolicy
info "Creating OpenShellPolicy..."
sed -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|MODEL_HOST_PLACEHOLDER|${MODEL_HOST}|g" \
    -e "s|MODEL_PORT_PLACEHOLDER|${MODEL_PORT}|g" \
    -e "s|VULN_API_IP_PLACEHOLDER|${VULN_API_IP}|g" \
    "${SCRIPT_DIR}/openshell-policy-crd.yaml" \
    | oc apply -f -

# Apply OpenShellSandbox
info "Creating OpenShellSandbox..."
# Config is now in ConfigMap, no inline JSON escaping needed
sed -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|REGISTRY_PLACEHOLDER|image-registry.openshift-image-registry.svc:5000/${NAMESPACE}|g" \
    -e "s|MODEL_ENDPOINT_PLACEHOLDER|${MODEL_ENDPOINT}|g" \
    -e "s|API_KEY_PLACEHOLDER|${OPENAI_API_KEY}|g" \
    -e "s|VULN_API_URL_PLACEHOLDER|${VULN_API_URL}|g" \
    "${SCRIPT_DIR}/openshell-sandbox.yaml" \
    | oc apply -f -

# --- 10. Wait for sandbox and patch NetworkPolicy ---

info "Waiting for sandbox to be ready..."
for _ in $(seq 1 60); do
    PHASE=$(oc get openshellsandbox opencode-dual -n "${NAMESPACE}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [ "$PHASE" = "Ready" ]; then
        info "✓ Sandbox is ready"
        break
    fi
    sleep 2
done

if [ "$PHASE" != "Ready" ]; then
    warn "Sandbox not ready (phase: ${PHASE}), file staging may fail"
fi

# Wait for sova-dashboard-ui to be ready (it has the openshell Python package)
info "Waiting for SOVA dashboard UI..."
oc wait --for=condition=Available deployment/sova-dashboard-ui \
    -n "${NAMESPACE}" --timeout=60s >/dev/null 2>&1 || warn "Dashboard UI not ready"

# --- 11. Stage files in sandbox using OpenShell API ---
# Use the OpenShell Python API via the sova-dashboard-ui pod to stage files.
# This must run AFTER the PVC is mounted (startup.sh runs before mount).

info "Staging files in sandbox using OpenShell API..."

# Execute staging directly via oc exec with inline Python
# IMPORTANT: Use single quotes to prevent bash variable expansion of $schema
oc exec -n "${NAMESPACE}" deployment/sova-dashboard-ui -- python3 -c '
from openshell.sandbox import SandboxClient
import sys
import json

client = SandboxClient(endpoint="openshell-kata:8080", tls=None, bearer_token=None, timeout=60.0)

try:
    # 1. Create directories
    print("Creating directories...")
    result = client.exec(
        sandbox="opencode-dual",
        command=["mkdir", "-p", "/sandbox/tmp", "/sandbox/.config/opencode", "/sandbox/.agents"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

    # 2. Copy files from image to sandbox
    print("Copying vuln_scan.py...")
    result = client.exec(
        sandbox="opencode-dual",
        command=["cp", "-f", "/home/user/workspace/vuln_scan.py", "/sandbox/"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

    print("Copying SECURITY_ANALYST.md...")
    result = client.exec(
        sandbox="opencode-dual",
        command=["cp", "-f", "/home/user/workspace/SECURITY_ANALYST.md", "/sandbox/"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

    # 3. Copy persona to .agents directory
    print("Copying persona to .agents...")
    result = client.exec(
        sandbox="opencode-dual",
        command=["cp", "-f", "/home/user/workspace/SECURITY_ANALYST.md", "/sandbox/.agents/security-analyst.md"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

    # 4. Write OpenCode config using json.dumps
    print("Writing OpenCode config...")
    config_dict = {
        "$schema": "https://opencode.ai/config.json",
        "model": "nemotron/nemotron-30b-vulkan",
        "autoupdate": False,
        "share": "disabled",
        "plugin": [],
        "provider": {
            "nemotron": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Nemotron (vLLM)",
                "options": {
                    "baseURL": "{env:OPENAI_BASE_URL}",
                    "apiKey": "{env:OPENAI_API_KEY}"
                },
                "models": {
                    "nemotron-30b-vulkan": {}
                }
            }
        }
    }
    config_json = json.dumps(config_dict, indent=2)
    result = client.exec(
        sandbox="opencode-dual",
        command=["sh", "-c", "cat > /sandbox/.config/opencode/config.json << " + "'" + "'" + "'" + "EOFCFG" + "'" + "'" + "'" + "\n" + config_json + "\nEOFCFG"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code != 0:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

    # 5. Verify all files
    print("Verifying staged files...")
    result = client.exec(
        sandbox="opencode-dual",
        command=["ls", "-lh", "/sandbox/vuln_scan.py", "/sandbox/.config/opencode/config.json", "/sandbox/.agents/security-analyst.md"],
        workspace="default",
        timeout_seconds=10,
        no_login_shell=True
    )
    if result.exit_code == 0:
        print("✓ All files staged successfully")
        print(result.stdout)
    else:
        print(f"ERROR: {result.stderr}")
        sys.exit(1)

finally:
    client.close()
' 2>&1

if [ $? -eq 0 ]; then
    info "✓ Files staged successfully in sandbox"
else
    warn "File staging failed - you may need to stage files manually"
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
oc get openshellpolicy,openshellsandbox -n "${NAMESPACE}" 2>/dev/null || true
echo ""
info "Pod status:"
oc get pod -n "${NAMESPACE}" | grep -E "(NAME|openshell|sova|vuln)" || true
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
info "  # Find supervisor pod: oc get pods -n ${NAMESPACE} | grep supervisor"
info "  # View logs: oc logs -n ${NAMESPACE} <supervisor-pod> -f"
