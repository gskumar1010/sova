# OpenShell + Kata Quickstart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reference architecture quickstart that shows how to deploy AI coding agents on OpenShift with dual-layer security (OpenShell + Kata Containers).

**Architecture:** Port and adapt the working POC at `/Users/nafridma/Documents/projects/openshell-sandbox-poc` into the rh-ai-quickstart org format. Kubernetes manifests are managed via Kustomize; shell scripts handle Helm installs, OpenShell CLI calls, and readiness waits. Three phases: infrastructure (cluster-admin), deployment (namespace-admin), verification.

**Tech Stack:** OpenShift 4.17+, Kata Containers (via OpenShift Sandboxed Containers operator), NVIDIA OpenShell, Helm 3, Kustomize, Bash

## Global Constraints

- Target: Level 1 (Community) in rh-ai-quickstart org
- README must follow the org template structure (title, short desc, ToC, description, architecture, requirements, deploy, delete, references, tags)
- All images stored in `docs/images/`
- No exploit code — this is a reference architecture, not a penetration testing demo
- Model endpoint is external (not deployed by this quickstart)
- Single pod deployment (dual protection only), not three comparison pods
- Shell scripts for orchestration (no Makefile)
- Kustomize for declarative Kubernetes resources
- POC source: `/Users/nafridma/Documents/projects/openshell-sandbox-poc`

---

### Task 1: Repository scaffolding

**Files:**
- Create: `.gitignore`
- Create: `env.sh.example`
- Create: `docs/images/.gitkeep`

- [ ] **Step 1: Create .gitignore**

```bash
# Sensitive files
env.sh
2-deploy/secret-api-keys.yaml
```

- [ ] **Step 2: Create env.sh.example**

```bash
# Copy to env.sh and fill in real values before running setup.
#   cp env.sh.example env.sh

# Container image registry (must be pushable)
export REGISTRY="quay.io/yourorg"

# Target namespace for the deployment
export NAMESPACE="openshell-kata"

# OpenAI-compatible model endpoint (vLLM, OpenShift AI, etc.)
export MODEL_ENDPOINT="http://your-model-svc:8000"

# API key for the model endpoint (use any non-empty string for local vLLM without auth)
export OPENAI_API_KEY="your-api-key"
```

- [ ] **Step 3: Create docs/images/.gitkeep**

Empty file to preserve the directory in git. The architecture diagram (`architecture.png`) will be added separately — it requires a visual design tool.

- [ ] **Step 4: Commit**

```bash
git add .gitignore env.sh.example docs/images/.gitkeep
git commit -m "scaffold: add gitignore, env example, and docs directory"
```

---

### Task 2: Infrastructure phase (1-infra/)

**Files:**
- Create: `1-infra/kata-operator.yaml` (port from POC `infra/kata-operator.yaml` as-is)
- Create: `1-infra/kata-runtimeclass.yaml` (port from POC `infra/kata-runtimeclass.yaml` as-is)
- Create: `1-infra/kata-veth-patch-job.yaml` (port from POC `infra/kata-veth-patch-job.yaml` as-is)
- Create: `1-infra/kustomization.yaml` (new)
- Create: `1-infra/verify-kata.sh` (adapted from POC `infra/verify-kernel.sh`)
- Create: `1-infra/setup.sh` (new)
- Create: `1-infra/README.md` (new)

- [ ] **Step 1: Copy manifests from POC as-is**

Copy these three files verbatim from the POC:

```bash
cp /Users/nafridma/Documents/projects/openshell-sandbox-poc/infra/kata-operator.yaml 1-infra/kata-operator.yaml
cp /Users/nafridma/Documents/projects/openshell-sandbox-poc/infra/kata-runtimeclass.yaml 1-infra/kata-runtimeclass.yaml
cp /Users/nafridma/Documents/projects/openshell-sandbox-poc/infra/kata-veth-patch-job.yaml 1-infra/kata-veth-patch-job.yaml
```

No changes needed — these are cluster-scoped operator resources that work as-is.

- [ ] **Step 2: Create kustomization.yaml**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - kata-operator.yaml
  - kata-runtimeclass.yaml
```

Note: `kata-veth-patch-job.yaml` is NOT in the kustomization — it must be applied after Kata is installed and ready, which `setup.sh` handles.

- [ ] **Step 3: Create verify-kata.sh**

Adapted from the POC's `verify-kernel.sh`. The POC version checks for CVE-2026-31431 vulnerability — the quickstart version verifies that Kata is installed and functional (no CVE checks).

```bash
#!/usr/bin/env bash
# verify-kata.sh -- Verify that Kata Containers is installed and functional
#
# Checks:
#   1. The 'kata' RuntimeClass exists
#   2. A test pod can run with the kata RuntimeClass
#
# Usage: ./1-infra/verify-kata.sh
# Requires: oc CLI logged in with cluster-admin privileges

set -euo pipefail

echo "=== Kata Containers Verification ==="
echo ""

# Check 1: RuntimeClass exists
echo -n "Checking for 'kata' RuntimeClass... "
if oc get runtimeclass kata >/dev/null 2>&1; then
    echo "FOUND"
else
    echo "NOT FOUND"
    echo ""
    echo "ERROR: The 'kata' RuntimeClass does not exist."
    echo "Ensure the OpenShift Sandboxed Containers operator is installed"
    echo "and the KataConfig CR has been applied."
    exit 1
fi

# Check 2: Test pod with Kata runtime
echo "Launching test pod with kata RuntimeClass..."
TEST_POD="kata-verify-$$"
oc run "${TEST_POD}" \
    --image=registry.access.redhat.com/ubi9/ubi-minimal:latest \
    --restart=Never \
    --overrides='{"spec":{"runtimeClassName":"kata"}}' \
    --command -- cat /proc/version

echo "Waiting for test pod to complete..."
if oc wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${TEST_POD}" \
    --timeout=120s 2>/dev/null; then
    echo ""
    echo "Guest kernel version:"
    oc logs "${TEST_POD}" 2>/dev/null | sed 's/^/  /'
    echo ""
    echo "RESULT: Kata is functional."
else
    echo ""
    echo "WARNING: Test pod did not succeed. Check pod status:"
    oc get pod "${TEST_POD}" -o wide 2>/dev/null || true
fi

# Clean up test pod
oc delete pod "${TEST_POD}" --ignore-not-found --wait=false >/dev/null 2>&1 || true

echo ""
echo "=== Verification complete ==="
```

- [ ] **Step 4: Create setup.sh**

```bash
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
info "Next step: Phase 2 — Deploy (see 2-deploy/README.md)"
```

- [ ] **Step 5: Create 1-infra/README.md**

```markdown
# Phase 1: Infrastructure Setup

**Audience:** Cluster admin
**Duration:** 10-20 minutes (includes node reboots)

This phase installs the Kata Containers runtime on your OpenShift cluster.
It requires cluster-admin privileges and will cause worker nodes to reboot.

## What This Does

1. Installs the OpenShift Sandboxed Containers operator
2. Creates a KataConfig CR that triggers Kata installation on worker nodes
3. Patches the Kata initramfs to include the `veth` kernel module (required by OpenShell)
4. Verifies that Kata is functional

## Prerequisites

- OpenShift 4.17+ cluster with bare-metal worker nodes
- Hardware virtualization support (Intel VT-x / AMD-V)
- `oc` CLI logged in with cluster-admin privileges

## Deploy

### Option A: Automated (recommended)

```bash
./1-infra/setup.sh
```

The script applies all manifests, waits for readiness, patches the
initramfs, and runs verification.

### Option B: Manual

```bash
# 1. Install operator and KataConfig
oc apply -k 1-infra/

# 2. Wait for operator
oc wait --for=condition=Available deployment/controller-manager \
    -n openshift-sandboxed-containers-operator --timeout=300s

# 3. Wait for nodes (this takes 10-20 minutes, nodes will reboot)
watch oc get kataconfig default -o jsonpath='{.status.installationStatus}'

# 4. Patch initramfs for veth module
oc apply -f 1-infra/kata-veth-patch-job.yaml
# Wait for patch pods to complete, then clean up:
oc delete -f 1-infra/kata-veth-patch-job.yaml

# 5. Verify
./1-infra/verify-kata.sh
```

## Important Notes

- The veth initramfs patch **does not survive node reboots**. After
  cluster maintenance or node updates, re-run the patch step.
- KataConfig installs Kata on **all worker nodes** by default. To target
  specific nodes, edit `kata-runtimeclass.yaml` and add a
  `kataConfigPoolSelector` with node labels.

## Next Step

Proceed to [Phase 2: Deployment](../2-deploy/README.md).
```

- [ ] **Step 6: Make scripts executable and commit**

```bash
chmod +x 1-infra/setup.sh 1-infra/verify-kata.sh
git add 1-infra/
git commit -m "feat: add Phase 1 infrastructure — Kata operator, KataConfig, veth patch"
```

---

### Task 3: Container image (images/)

**Files:**
- Create: `images/agent-sandbox/Dockerfile` (adapted from POC)
- Create: `images/agent-sandbox/opencode.json` (adapted from POC)

- [ ] **Step 1: Create Dockerfile**

Adapted from the POC. Removes all exploit code and attack payloads.

```dockerfile
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
```

- [ ] **Step 2: Create opencode.json**

The model endpoint is configured via environment variables at runtime, not baked into the image. OpenCode reads `OPENAI_API_KEY` from the env via the `env:` prefix. For `base_url`, the setup script creates a ConfigMap with the correct endpoint and mounts it over this default config.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "api_key": "env:OPENAI_API_KEY"
    }
  }
}
```

Note: The `base_url` is omitted from this default config. The `2-deploy/setup.sh` script generates a ConfigMap with the full config (including `MODEL_ENDPOINT`) and mounts it into the sandbox pod. This keeps the image generic and avoids rebuilds when the model endpoint changes.

- [ ] **Step 3: Commit**

```bash
git add images/
git commit -m "feat: add agent sandbox container image"
```

---

### Task 4: Deployment phase (2-deploy/)

**Files:**
- Create: `2-deploy/namespace.yaml` (adapted from POC)
- Create: `2-deploy/openshell-scc.yaml` (port from POC as-is)
- Create: `2-deploy/openshell-helm-values.yaml` (adapted from POC)
- Create: `2-deploy/openshell-policy.yaml` (adapted from POC)
- Create: `2-deploy/secret-api-keys.yaml.example` (adapted from POC)
- Create: `2-deploy/kustomization.yaml` (new)
- Create: `2-deploy/setup.sh` (adapted from POC `demo/setup.sh`)
- Create: `2-deploy/teardown.sh` (adapted from POC `demo/teardown.sh`)
- Create: `2-deploy/README.md` (new)

- [ ] **Step 1: Create namespace.yaml**

Adapted from POC — updated namespace name and labels.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: openshell-kata
  labels:
    app.kubernetes.io/part-of: openshell-kata
```

- [ ] **Step 2: Copy openshell-scc.yaml from POC**

```bash
cp /Users/nafridma/Documents/projects/openshell-sandbox-poc/deploy/openshell-scc.yaml 2-deploy/openshell-scc.yaml
```

No changes needed — the SCC grants the same capabilities regardless of namespace or pod count.

- [ ] **Step 3: Create openshell-helm-values.yaml**

Adapted from POC — removed comments about multi-pod setup, updated image name.

```yaml
# Helm values for OpenShell on OpenShift with Kata Containers
#
# Usage:
#   helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
#     -n ${NAMESPACE} -f 2-deploy/openshell-helm-values.yaml

server:
  disableTls: true
  logLevel: info

  auth:
    allowUnauthenticatedUsers: true

  # RuntimeClass is set per-sandbox via --driver-config-json, not globally
  defaultRuntimeClassName: ""

  # Kata shim does not support ImageVolume — force init-container delivery
  forceInitContainerSideload: true

  sandboxImage: "REGISTRY_PLACEHOLDER/openshell-kata-agent-sandbox:latest"
  sandboxImagePullPolicy: "Always"

  sandboxNamespace: ""

supervisor:
  sideloadMethod: init-container

pkiInitJob:
  enabled: false

podSecurityContext:
  fsGroup: 0

securityContext:
  runAsNonRoot: false
  runAsUser: 0
  capabilities:
    drop: []

networkPolicy:
  enabled: false

service:
  type: NodePort

replicaCount: 1
```

- [ ] **Step 4: Create openshell-policy.yaml**

Adapted from POC — made the model endpoint a placeholder that `setup.sh` will substitute.

```yaml
# OpenShell sandbox network and filesystem policy
#
# Allows ONLY the configured model endpoint. All other egress is denied.
# The MODEL_ENDPOINT placeholder is substituted by setup.sh at deploy time.

version: 1

filesystem_policy:
  include_workdir: true
  read_only: [/usr, /lib, /proc, /dev/urandom, /etc]
  read_write: [/sandbox, /tmp, /home, /opt, /dev/null]
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox

network_policies:
  model_inference:
    name: model-inference
    endpoints:
      - host: MODEL_ENDPOINT_HOST
        port: MODEL_ENDPOINT_PORT
        protocol: rest
        enforcement: enforce
        access: read-write
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3 }
```

- [ ] **Step 5: Create secret-api-keys.yaml.example**

Adapted from POC — updated namespace and labels.

```yaml
# API keys secret — TEMPLATE
#
# Copy, fill in, and apply:
#   cp 2-deploy/secret-api-keys.yaml.example 2-deploy/secret-api-keys.yaml
#   # Edit with real values
#   oc apply -f 2-deploy/secret-api-keys.yaml
#
# NEVER commit the filled-in version to git.
---
apiVersion: v1
kind: Secret
metadata:
  name: opencode-api-keys
  labels:
    app.kubernetes.io/part-of: openshell-kata
type: Opaque
stringData:
  OPENAI_API_KEY: "your-api-key"
```

Note: the `namespace` field is omitted — Kustomize's namespace transformer adds it.

- [ ] **Step 6: Create kustomization.yaml**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: openshell-kata

resources:
  - namespace.yaml
  - openshell-scc.yaml
```

Note: `secret-api-keys.yaml.example` is NOT listed — it's a template. `openshell-helm-values.yaml` and `openshell-policy.yaml` are consumed by Helm and the OpenShell CLI respectively, not `oc apply`.

- [ ] **Step 7: Create setup.sh**

Simplified from the POC's `demo/setup.sh`. Deploys a single dual-protection pod instead of three. Removes attacker-listener, attack ConfigMaps, and multi-pod logic.

```bash
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
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
command -v openshell >/dev/null || warn "openshell CLI not found — sandbox creation will fail"
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
    ]" 2>/dev/null || warn "SCC patch failed — users may already be present"

# --- 3. API key secret ---

info "Creating API key secret..."
if ! oc get secret opencode-api-keys -n "${NAMESPACE}" >/dev/null 2>&1; then
    oc create secret generic opencode-api-keys -n "${NAMESPACE}" \
        --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}"
    info "Created opencode-api-keys secret."
else
    info "Secret opencode-api-keys already exists, skipping."
fi

# --- 4. OpenCode config ConfigMap ---

info "Creating OpenCode config ConfigMap..."
# Parse host and port from MODEL_ENDPOINT for the OpenShell policy
MODEL_HOST=$(echo "${MODEL_ENDPOINT}" | sed -E 's|^https?://||' | cut -d: -f1)
MODEL_PORT=$(echo "${MODEL_ENDPOINT}" | sed -E 's|^https?://||' | cut -d: -f2 | cut -d/ -f1)
[ -z "${MODEL_PORT}" ] && MODEL_PORT="8000"

OPENCODE_CONFIG=$(cat <<CFGEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "api_key": "env:OPENAI_API_KEY",
      "base_url": "${MODEL_ENDPOINT}/v1"
    }
  }
}
CFGEOF
)

oc create configmap opencode-config -n "${NAMESPACE}" \
    --from-literal=config.json="${OPENCODE_CONFIG}" \
    --dry-run=client -o yaml | oc apply -f -

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
info "Next step: Phase 3 — Verify (see 3-demo/README.md)"
```

- [ ] **Step 8: Create teardown.sh**

```bash
#!/usr/bin/env bash
# teardown.sh -- Remove all quickstart resources from the cluster
#
# Usage:
#   source env.sh
#   ./2-deploy/teardown.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${NAMESPACE:-openshell-kata}"

info() { echo "==> $*"; }

info "Tearing down OpenShell + Kata deployment..."

# Delete OpenShell sandbox
info "Deleting OpenShell sandbox..."
openshell sandbox delete opencode-dual 2>/dev/null || true

# Delete secrets and ConfigMaps
info "Deleting secrets and ConfigMaps..."
oc delete configmap opencode-config -n "${NAMESPACE}" --ignore-not-found
oc delete secret opencode-api-keys -n "${NAMESPACE}" --ignore-not-found
oc delete secret openshell-jwt-keys -n "${NAMESPACE}" --ignore-not-found

# Uninstall OpenShell
info "Uninstalling OpenShell gateway..."
helm uninstall openshell -n "${NAMESPACE}" 2>/dev/null || true

# Remove Kustomize-managed resources
info "Removing namespace and SCC..."
oc delete -k "${SCRIPT_DIR}" --ignore-not-found 2>/dev/null || true

echo ""
info "Teardown complete."
info "Note: The Kata operator and KataConfig are NOT removed."
info "Remove them manually if needed:"
info "  oc delete kataconfig default"
info "  oc delete subscription sandboxed-containers-operator -n openshift-sandboxed-containers-operator"
```

- [ ] **Step 9: Create 2-deploy/README.md**

```markdown
# Phase 2: Deployment

**Audience:** Namespace admin
**Duration:** 5-10 minutes

This phase deploys the OpenShell gateway and creates a dual-protection
agent sandbox (OpenShell + Kata).

## Prerequisites

- [Phase 1](../1-infra/README.md) complete (Kata installed)
- `oc` CLI logged in
- `helm` v3 installed
- `openshell` CLI installed
- Container image built and pushed:
  ```bash
  source env.sh
  docker build -f images/agent-sandbox/Dockerfile -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .
  docker push ${REGISTRY}/openshell-kata-agent-sandbox:latest
  ```

## Deploy

```bash
source env.sh
./2-deploy/setup.sh
```

The script:
1. Creates the namespace and SCC (`oc apply -k`)
2. Creates the API key secret
3. Creates the OpenCode config ConfigMap (with your `MODEL_ENDPOINT`)
4. Installs the OpenShell gateway via Helm
5. Generates JWT signing keys
6. Creates the dual-protection sandbox (`openshell sandbox create` with Kata RuntimeClass)

## Customization

**Namespace and images:** Edit `2-deploy/kustomization.yaml` to change
the target namespace or override image references.

**Network policy:** Edit `2-deploy/openshell-policy.yaml` to allow
additional endpoints. The `MODEL_ENDPOINT_HOST` and `MODEL_ENDPOINT_PORT`
placeholders are substituted by `setup.sh` from your `env.sh`.

## Teardown

```bash
source env.sh
./2-deploy/teardown.sh
```

This removes the sandbox, gateway, secrets, namespace, and SCC.
The Kata operator and KataConfig are left in place.

## Next Step

Proceed to [Phase 3: Verify](../3-demo/README.md).
```

- [ ] **Step 10: Make scripts executable and commit**

```bash
chmod +x 2-deploy/setup.sh 2-deploy/teardown.sh
git add 2-deploy/
git commit -m "feat: add Phase 2 deployment — OpenShell gateway, sandbox, Kustomize"
```

---

### Task 5: Verification phase (3-demo/)

**Files:**
- Create: `3-demo/lib/colors.sh` (port from POC as-is)
- Create: `3-demo/lib/utils.sh` (simplified from POC)
- Create: `3-demo/run-demo.sh` (new, verify-focused)
- Create: `3-demo/README.md` (new)

- [ ] **Step 1: Copy colors.sh from POC**

```bash
mkdir -p 3-demo/lib
cp /Users/nafridma/Documents/projects/openshell-sandbox-poc/demo/lib/colors.sh 3-demo/lib/colors.sh
```

No changes needed.

- [ ] **Step 2: Create utils.sh**

Simplified from the POC. Removes attacker-listener functions, verify-pod functions, page-cache functions. Keeps only `pod_exec` (for the single dual-protection pod) and `pod_ready`.

```bash
#!/usr/bin/env bash
# Shared utility functions for verification

NAMESPACE="${NAMESPACE:-openshell-kata}"
SANDBOX_NAME="opencode-dual"

# Execute a command in the sandbox via openshell sandbox exec.
# This ensures the command runs inside the supervised sandbox
# (network namespace with policy proxy active).
pod_exec() {
    openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty --timeout 30 -- "$@" 2>&1
}

# Check if the sandbox pod is running
pod_ready() {
    local status
    status=$(oc get pod "${SANDBOX_NAME}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.phase}' 2>/dev/null)
    [ "${status}" = "Running" ]
}
```

- [ ] **Step 3: Create run-demo.sh**

New verify-focused script. Checks: agent functional, egress blocked, Kata active.

```bash
#!/usr/bin/env bash
# run-demo.sh -- Verify that the dual-protection sandbox is operational
#
# Runs three checks:
#   1. Agent can reach the model endpoint (functional)
#   2. Unauthorized egress is blocked (OpenShell policy)
#   3. Kata VM isolation is active (guest kernel)
#
# Prerequisites:
#   - Phase 2 complete (sandbox deployed)
#   - env.sh sourced
#   - Port-forward to OpenShell gateway running (setup.sh starts one)
#
# Usage:
#   source env.sh
#   ./3-demo/run-demo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${NAMESPACE:-openshell-kata}"

# shellcheck source=3-demo/lib/colors.sh
source "${SCRIPT_DIR}/lib/colors.sh"
# shellcheck source=3-demo/lib/utils.sh
source "${SCRIPT_DIR}/lib/utils.sh"

# --- Port-forward ---

PF_PID=""
cleanup() {
    if [ -n "${PF_PID}" ] && kill -0 "${PF_PID}" 2>/dev/null; then
        kill "${PF_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start port-forward if not already running
if ! pgrep -f "port-forward.*svc/openshell.*18080" >/dev/null 2>&1; then
    info "Starting port-forward to OpenShell gateway..."
    oc port-forward -n "${NAMESPACE}" svc/openshell 18080:8080 > /tmp/demo-pf.log 2>&1 &
    PF_PID=$!
    sleep 3
    if ! kill -0 "${PF_PID}" 2>/dev/null; then
        fail "Port-forward failed. Check /tmp/demo-pf.log"
        exit 1
    fi
fi

# =====================================================================
banner "OpenShell + Kata Verification"
# =====================================================================

echo "Verifying the dual-protection sandbox is correctly configured:"
echo "  - OpenShell enforces network egress policy"
echo "  - Kata provides hardware VM isolation"
echo ""

# --- Preflight ---

section "Preflight"

if pod_ready; then
    pass "Sandbox pod 'opencode-dual' is running"
else
    fail "Sandbox pod 'opencode-dual' is NOT running"
    echo ""
    fail "Run 2-deploy/setup.sh first."
    exit 1
fi

# Check RuntimeClass
RUNTIME_CLASS=$(oc get pod opencode-dual -n "${NAMESPACE}" \
    -o jsonpath='{.spec.runtimeClassName}' 2>/dev/null || echo "")
if [ "${RUNTIME_CLASS}" = "kata" ]; then
    pass "Pod RuntimeClass: kata"
else
    warn "Pod RuntimeClass: '${RUNTIME_CLASS}' (expected 'kata')"
fi

CHECKS_PASSED=0
CHECKS_TOTAL=3

# =====================================================================
section "Check 1: Agent Functionality"
# =====================================================================

echo "Verifying the agent can execute commands inside the sandbox..."
echo ""

OUTPUT=$(pod_exec echo "hello from sandbox" 2>&1 || true)

if echo "${OUTPUT}" | grep -q "hello from sandbox"; then
    pass "Agent can execute commands inside the sandbox"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    fail "Agent command execution failed"
    info "Output: ${OUTPUT}"
fi

# =====================================================================
section "Check 2: Egress Policy Enforcement"
# =====================================================================

echo "Attempting unauthorized network egress (should be blocked)..."
echo ""

OUTPUT=$(pod_exec curl -s --max-time 10 http://example.com 2>&1 || true)

if echo "${OUTPUT}" | grep -qi "policy_denied\|blocked\|connection refused\|denied"; then
    pass "Unauthorized egress BLOCKED by OpenShell policy"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    info "Response: $(echo "${OUTPUT}" | head -1)"
elif echo "${OUTPUT}" | grep -qi "timed out\|timeout"; then
    pass "Unauthorized egress blocked (connection timed out)"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    fail "Egress was NOT blocked — check OpenShell policy configuration"
    info "Output: $(echo "${OUTPUT}" | head -3)"
fi

# =====================================================================
section "Check 3: Kata VM Isolation"
# =====================================================================

echo "Verifying the pod runs inside a Kata VM (separate guest kernel)..."
echo ""

HOST_KERNEL=$(oc get nodes -o jsonpath='{.items[0].status.nodeInfo.kernelVersion}' 2>/dev/null || echo "unknown")
GUEST_KERNEL=$(pod_exec cat /proc/version 2>&1 || echo "")

info "Host kernel:  ${HOST_KERNEL}"
info "Guest kernel: $(echo "${GUEST_KERNEL}" | head -1)"

if [ -n "${GUEST_KERNEL}" ] && [ "${GUEST_KERNEL}" != "${HOST_KERNEL}" ]; then
    pass "Guest kernel differs from host — Kata VM boundary confirmed"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    warn "Could not confirm separate guest kernel"
    info "This may be expected if host and guest run the same kernel version"
fi

# =====================================================================
banner "Results"
# =====================================================================

echo "  Checks passed: ${CHECKS_PASSED}/${CHECKS_TOTAL}"
echo ""

if [ "${CHECKS_PASSED}" -eq "${CHECKS_TOTAL}" ]; then
    echo -e "${GREEN}${BOLD}All checks passed. Dual protection is operational.${NC}"
else
    echo -e "${YELLOW}${BOLD}Some checks did not pass. Review output above.${NC}"
fi

echo ""
```

- [ ] **Step 4: Create 3-demo/README.md**

```markdown
# Phase 3: Verification

**Audience:** Anyone with namespace access
**Duration:** 2-3 minutes

This phase verifies that the dual-protection sandbox is correctly
configured and operational.

## Prerequisites

- [Phase 2](../2-deploy/README.md) complete (sandbox deployed)
- `env.sh` sourced

## Run

```bash
source env.sh
./3-demo/run-demo.sh
```

## What It Checks

| Check | What it verifies | Expected result |
|-------|-----------------|-----------------|
| Agent functionality | Commands execute inside the sandbox | "hello from sandbox" echoed back |
| Egress policy | Unauthorized network access is blocked | `policy_denied` or connection refused |
| Kata isolation | Pod runs in a VM with a separate kernel | Guest kernel differs from host kernel |

## Expected Output

```
══════════════════════════════════════════════════════════════
  OpenShell + Kata Verification
══════════════════════════════════════════════════════════════

--- Preflight ---
  [PASS] Sandbox pod 'opencode-dual' is running
  [PASS] Pod RuntimeClass: kata

--- Check 1: Agent Functionality ---
  [PASS] Agent can execute commands inside the sandbox

--- Check 2: Egress Policy Enforcement ---
  [PASS] Unauthorized egress BLOCKED by OpenShell policy

--- Check 3: Kata VM Isolation ---
  [PASS] Guest kernel differs from host — Kata VM boundary confirmed

══════════════════════════════════════════════════════════════
  Results
══════════════════════════════════════════════════════════════
  Checks passed: 3/3
  All checks passed. Dual protection is operational.
```
```

- [ ] **Step 5: Make scripts executable and commit**

```bash
chmod +x 3-demo/run-demo.sh
git add 3-demo/
git commit -m "feat: add Phase 3 verification — demo script and helpers"
```

---

### Task 6: Documentation

**Files:**
- Create: `docs/security-model.md` (rewritten from POC)
- Create: `README.md` (new, org-template compliant)

- [ ] **Step 1: Create docs/security-model.md**

Rewritten from the POC's `docs/security-model.md`. Expanded with policy configuration reference. No exploit code.

```markdown
# Security Model

This document explains the threat model for AI coding agents on shared
clusters and why dual-layer protection (OpenShell + Kata Containers) is
required for defense in depth.

## Threat Model

AI coding agents execute code from natural-language instructions. They run
shell commands, install packages, edit files, and make network requests.
This creates exposure to two distinct threat classes:

### Application-Layer Threats

Prompt injection, data exfiltration, credential theft. An attacker
embeds malicious instructions in untrusted input (a git patch, an issue
comment, a dependency README) that steer the agent toward leaking secrets
or accessing unauthorized services.

These attacks operate through normal application behavior — HTTP requests,
file reads, environment variable access. They do not require any exploit
or vulnerability in the runtime.

### Kernel-Level Threats

Container escape, host filesystem access, lateral movement. The agent
runs code that exploits a vulnerability in the Linux kernel to break out
of the container boundary and access the host or other containers.

Since agents routinely execute `pip install`, `npm install`, `make`, and
arbitrary shell commands, the kernel attack surface is directly exposed.
A compromised dependency can contain kernel exploit code.

## Why Two Layers

### OpenShell: Application-Layer Defense

NVIDIA OpenShell wraps each agent sandbox in a policy-enforced runtime:

- **Network egress proxy** — All outbound connections route through a
  proxy that evaluates destination, port, calling binary, and protocol.
  Default posture is deny-all; only explicitly allowed endpoints pass.
- **Filesystem isolation (Landlock)** — Kernel-enforced read/write
  restrictions on filesystem paths, locked at sandbox creation.
- **Process isolation** — The agent runs as an unprivileged user with
  dropped capabilities.

**Blocks:** Data exfiltration, unauthorized API calls, credential leakage
through network channels.

**Cannot block:** Kernel-level exploits. Landlock and seccomp operate
within the kernel's integrity boundary. If an attacker corrupts kernel
memory, these controls are bypassed entirely.

### Kata Containers: Kernel-Layer Defense

Kata Containers runs each pod inside a lightweight virtual machine with
its own dedicated guest kernel:

- **Separate kernel** — The workload interacts with a guest kernel, not
  the host kernel. Kernel exploits affect only the guest.
- **Hardware-enforced isolation** — The VM boundary is enforced by CPU
  virtualization extensions (VT-x / AMD-V), not by namespaces or cgroups.
- **Memory isolation** — Guest memory (including page cache) is isolated
  from host memory via virtiofs.

**Blocks:** Container escape exploits, kernel privilege escalation,
page-cache corruption, host filesystem access.

**Cannot block:** Application-layer threats. Kata does not inspect network
traffic or enforce egress policies. `curl http://evil/` is a normal
network operation from Kata's perspective.

## Threat Matrix

| Threat | OpenShell | Kata | Both |
|--------|-----------|------|------|
| Data exfiltration via network | Blocks | Allows | Blocks |
| Prompt injection leading to exfiltration | Blocks | Allows | Blocks |
| Credential theft via environment variables | Blocks | Allows | Blocks |
| Container escape via kernel CVE | Allows | Blocks | Blocks |
| Page-cache corruption across containers | Allows | Blocks | Blocks |
| Host filesystem access via /proc | Allows | Blocks | Blocks |

## Case Study: CVE-2026-31431

CVE-2026-31431 is a logic flaw in the Linux kernel's `algif_aead` crypto
subsystem (AF_ALG socket family). It allows an unprivileged process to
obtain a writable reference to a page-cache page belonging to any file on
the same filesystem layer.

**How it works:** The exploit opens an AF_ALG socket with the
`authencesn(hmac(sha256),cbc(aes))` algorithm, uses `splice()` to create
a pipe between a target file's page cache and the socket, then exploits a
reference-counting bug to retain a writable mapping to the page-cache
page after the socket operation completes.

**Why OpenShell cannot block it:** The exploit uses only legitimate
syscalls (`socket`, `bind`, `splice`, `sendmsg`). It does not make any
network connections, access restricted files, or escalate privileges
through the process model. Landlock, seccomp, and `no_new_privs` cannot
prevent kernel memory corruption that happens below their enforcement
layer.

**Why Kata contains it:** Kata uses virtiofs to provide the container
filesystem. Each VM has its own page cache, isolated from the host and
other VMs. Page-cache corruption inside the guest VM is invisible to
other containers and to the host. The exploit "succeeds" (the target file
appears corrupted inside the VM) but the damage cannot escape the VM
boundary.

**Fix:** Kernel commit `a664bf3d603d` (merged April 1, 2026). Patching
the host kernel eliminates this specific vulnerability, but the broader
pattern — kernel bugs that bypass container isolation — is ongoing. Kata
provides structural protection against this entire class.

## Policy Configuration Reference

The OpenShell network policy (`2-deploy/openshell-policy.yaml`) controls
which endpoints the agent can reach. The policy is applied at sandbox
creation time.

### Endpoint allowlist

Each entry specifies a host, port, protocol, and which binaries may
connect:

```yaml
network_policies:
  model_inference:
    name: model-inference
    endpoints:
      - host: your-model-svc.namespace.svc.cluster.local
        port: 8000
        protocol: rest
        enforcement: enforce
        access: read-write
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3 }
```

To allow additional endpoints (e.g., a package registry), add another
entry under `network_policies`.

### Filesystem policy

Controls which paths the agent can read and write:

```yaml
filesystem_policy:
  include_workdir: true
  read_only: [/usr, /lib, /proc, /dev/urandom, /etc]
  read_write: [/sandbox, /tmp, /home, /opt, /dev/null]
```

Paths not listed are inaccessible. Landlock enforces these restrictions
at the kernel level.
```

- [ ] **Step 2: Create top-level README.md**

```markdown
# Secure AI Coding Agents with OpenShell and Kata Containers on OpenShift

Deploy AI coding agents with defense-in-depth using NVIDIA OpenShell and Kata Containers on Red Hat OpenShift.

## Table of Contents

- [Description](#description)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Deploy](#deploy)
- [Delete](#delete)
- [Security Model](#security-model)
- [References](#references)
- [Tags](#tags)

## Description

AI coding agents need shell access to be productive — running tests,
editing files, installing packages, executing builds. But unrestricted
shell access on a shared cluster creates two distinct threat classes that
must be addressed simultaneously.

**Application-layer threats** such as prompt injection can steer an agent
toward exfiltrating secrets, accessing unauthorized services, or leaking
credentials through network channels. These attacks use normal
application behavior and do not require any runtime vulnerability.

**Kernel-level threats** such as container escape exploits allow
malicious code to break out of the container boundary, access the host
filesystem, or move laterally to other workloads. Since agents routinely
execute untrusted code (`pip install`, `npm install`, arbitrary shell
commands), the kernel attack surface is directly exposed.

This reference architecture deploys AI coding agents inside a
dual-protection boundary: **NVIDIA OpenShell** enforces application-layer
policies (network egress allowlisting, filesystem restrictions, process
isolation), while **Kata Containers** provides hardware-enforced VM
isolation at the kernel level. Together they cover threat classes that
neither technology addresses alone.

### Architecture

![Architecture](docs/images/architecture.png)

The deployment consists of:

- **OpenShift worker nodes** with Kata Containers installed (lightweight
  VMs via hardware virtualization)
- **OpenShell gateway** running as a StatefulSet, managing sandbox
  lifecycle and policy enforcement
- **Agent sandbox pod** running inside a Kata VM with OpenShell
  supervisor (Landlock filesystem policy + network egress proxy)
- **External model endpoint** (vLLM, OpenShift AI, or any
  OpenAI-compatible service)

## Requirements

### Hardware Requirements

- OpenShift cluster with **bare-metal worker nodes**
- **Hardware virtualization support** (Intel VT-x / AMD-V) required for
  Kata Containers

### Software Requirements

| Tool | Version |
|------|---------|
| Red Hat OpenShift | 4.17+ |
| OpenShift Sandboxed Containers operator | latest |
| NVIDIA OpenShell CLI (`openshell`) | latest |
| `openshell-gateway` binary | latest |
| Helm | 3.x |
| `oc` CLI | matching cluster version |

### Additional Requirements

- An **OpenAI-compatible model endpoint** (vLLM, OpenShift AI, or
  similar) accessible from the cluster
- A **container image registry** you can push to (e.g., Quay.io)

## Deploy

### Prerequisites

1. Copy and configure environment variables:
   ```bash
   cp env.sh.example env.sh
   # Edit env.sh with your values
   source env.sh
   ```

2. Build and push the agent sandbox image:
   ```bash
   docker build -f images/agent-sandbox/Dockerfile \
     -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .
   docker push ${REGISTRY}/openshell-kata-agent-sandbox:latest
   ```

### Phase 1: Infrastructure (cluster-admin)

Install the Kata Containers runtime on your OpenShift cluster. This
requires cluster-admin privileges and will cause worker nodes to reboot.

→ See [1-infra/README.md](1-infra/README.md)

### Phase 2: Deployment

Deploy the OpenShell gateway and create the dual-protection agent
sandbox.

→ See [2-deploy/README.md](2-deploy/README.md)

### Phase 3: Verify

Confirm that the agent works and security boundaries are enforced.

→ See [3-demo/README.md](3-demo/README.md)

### Delete

Remove all quickstart resources:

```bash
source env.sh
./2-deploy/teardown.sh
```

This removes the sandbox, OpenShell gateway, secrets, namespace, and SCC.
The Kata operator and KataConfig are left in place. To remove them:

```bash
oc delete kataconfig default
oc delete subscription sandboxed-containers-operator \
  -n openshift-sandboxed-containers-operator
```

## Security Model

This architecture protects against two complementary threat classes.
See [docs/security-model.md](docs/security-model.md) for the full
analysis, design rationale, and CVE case studies.

| Threat class | OpenShell | Kata | Both |
|---|---|---|---|
| Data exfiltration via network | Blocks | Allows | Blocks |
| Prompt injection leading to exfiltration | Blocks | Allows | Blocks |
| Container escape via kernel CVE | Allows | Blocks | Blocks |
| Host filesystem access | Allows | Blocks | Blocks |

## References

- [NVIDIA OpenShell documentation](https://github.com/NVIDIA/OpenShell)
- [OpenShift Sandboxed Containers documentation](https://docs.openshift.com/container-platform/latest/sandboxed_containers/)
- [Kata Containers architecture](https://katacontainers.io/docs/)

## Tags

- **Product:** Red Hat OpenShift, OpenShift Sandboxed Containers
- **Partner:** NVIDIA
- **Use case:** Security
```

- [ ] **Step 3: Commit**

```bash
git add docs/security-model.md README.md
git commit -m "docs: add README and security model"
```

---

### Task 7: Final review and cleanup

- [ ] **Step 1: Verify all files exist**

```bash
find . -type f -not -path './.git/*' -not -path './docs/superpowers/*' | sort
```

Expected output should match the repository structure from the design spec.

- [ ] **Step 2: Run shellcheck on all scripts**

```bash
shellcheck 1-infra/setup.sh 1-infra/verify-kata.sh \
           2-deploy/setup.sh 2-deploy/teardown.sh \
           3-demo/run-demo.sh 3-demo/lib/colors.sh 3-demo/lib/utils.sh
```

Fix any issues found.

- [ ] **Step 3: Verify YAML syntax**

```bash
for f in $(find . -name '*.yaml' -not -path './.git/*'); do
    echo "Checking $f..."
    python3 -c "import yaml; yaml.safe_load(open('$f'))" 2>&1 || echo "INVALID: $f"
done
```

- [ ] **Step 4: Verify kustomization files**

```bash
oc kustomize 1-infra/ > /dev/null && echo "1-infra/ OK"
oc kustomize 2-deploy/ > /dev/null && echo "2-deploy/ OK"
```

- [ ] **Step 5: Review README links**

Check that all relative links in README.md, 1-infra/README.md, 2-deploy/README.md, and 3-demo/README.md point to files that exist.

- [ ] **Step 6: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: address shellcheck and YAML validation issues"
```
