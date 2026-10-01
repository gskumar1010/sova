# Phase 2: Deployment

**Audience:** Namespace admin
**Duration:** 10-15 minutes

This phase deploys the OpenShell gateway, SOVA vulnerability orchestrator API,
SOVA dashboard UI, and creates a dual-protection security analyst sandbox
(OpenShell + Kata) with **enforced policy controls** via the Kubernetes Operator.

## Prerequisites

- [Phase 1](../1-infra/README.md) complete (Kata installed)
- `oc` CLI logged in
- `helm` v3 installed
- `podman` installed
- **Cluster admin access** (for operator installation - one-time)
- Internal image registry configured (see Phase 1 Initial Setup)

### Create Namespace and Secrets

Before deploying SOVA, create the target namespace and image pull secret:

```bash
source env.sh

# Create namespace
oc create namespace ${NAMESPACE}

# Create GitHub Container Registry pull secret (if using ghcr.io images)
oc create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<github-pat> \
  -n openshell-kata
```

**Note:** The `setup-operator.sh` script will automatically build and push all required
images (agent-sandbox, vuln-orchestrator-api, sova-dashboard-ui) to your cluster's internal
registry unless you set `SKIP_BUILD=1`.

## Deploy

### Step 1: Install OpenShell Kubernetes Operator (One-time, Cluster-wide)

**Important:** Ensure you've created the namespace and ghcr-pull secret first (see Prerequisites above).

```bash
source env.sh
./2-deploy/install-openshell-operator.sh
```

**What this does:**
- Clones the OpenShell Kubernetes Operator repository
- Installs CRDs (`OpenShellPolicy`, `OpenShellProvider`, `OpenShellSandbox`)
- Deploys the operator controller to `openshell-operator-system` namespace
- Configures operator to use your existing gateway

**Verify installation:**
```bash
# Check CRDs are installed
oc get crd | grep openshell

# Check operator pod is running
oc get pods -n openshell-operator-system
```

**Note:** This step only needs to be done **once per cluster**. The operator runs cluster-wide
and can manage sandboxes in multiple namespaces.

### Step 2: Deploy SOVA with Enforced Policies

```bash
source env.sh
./2-deploy/setup-operator.sh
```

**What this does:**
1. Builds and pushes SOVA app images (vuln-orchestrator-api, sova-dashboard-ui)
2. Creates the namespace and SCC (`oc apply -k`)
3. Deploys the vulnerability orchestrator API
4. Deploys the SOVA dashboard UI with OpenShift Route
5. Creates the API key secret for model access
6. **Adds required annotation to secret** for operator to use it
7. Installs the OpenShell gateway via Helm
8. **Creates OpenShell CRDs with enforced policies:**
   - `OpenShellPolicy` - Security constraints (filesystem, network, process)
   - `OpenShellProvider` - Credential management
   - `OpenShellSandbox` - Agent sandbox with policy enforcement
9. Waits for operator to reconcile and create the sandbox pod
10. Stages vuln_scan.py tool and SECURITY_ANALYST.md persona into sandbox workspace

**Verify deployment:**
```bash
# Check operator resources are ready
oc get openshellpolicy,openshellprovider,openshellsandbox -n ${NAMESPACE}

# Expected output:
# NAME                                                            TYPE                MODE     READY   AGE
# openshellprovider.openshell.lenshq.io/opencode-model-provider   openai-compatible   Copied   True    5m
#
# NAME                                                    READY   AGE
# openshellpolicy.openshell.lenshq.io/vuln-agent-policy   True    5m
#
# NAME                                                 READY   PHASE   SANDBOX                                AGE
# openshellsandbox.openshell.lenshq.io/opencode-dual   True    Ready   22958878-6da3-4fd3-b571-e98bf13f16e3   5m

# Check sandbox pod is running
oc get pods -n ${NAMESPACE}
```

## 🎯 Key Improvement: Policy Enforcement

**Previous approach (`setup.sh`):**
- ❌ Used CLI command `openshell sandbox create --policy`
- ❌ Policy was **ignored** in Kubernetes mode
- ❌ No declarative management

**New approach (`setup-operator.sh`):**
- ✅ Uses Kubernetes CRDs for declarative policy management
- ✅ Policy is **actually enforced** via the operator
- ✅ Hot-reloadable network policies
- ✅ GitOps-ready
- ✅ Applied policy hash visible: `oc get openshellsandbox -o yaml | grep appliedPolicyHash`

See [POLICY-ENFORCEMENT-EXPLAINED.md](./POLICY-ENFORCEMENT-EXPLAINED.md) for detailed explanation.

## Customization

### Network Policy

Edit `2-deploy/openshell-policy-crd.yaml` to modify network access rules:

```yaml
spec:
  networkPolicies:
    my_new_endpoint:
      name: my-new-endpoint
      endpoints:
        - host: api.example.com
          port: 443
          protocol: rest
          enforcement: enforce
      binaries:
        - path: /usr/bin/curl
```

**Update at runtime:**
```bash
oc edit openshellpolicy vuln-agent-policy -n ${NAMESPACE}
```

Changes to `networkPolicies` are **hot-reloaded** without pod restart!

### Filesystem and Process Policies

Edit `2-deploy/openshell-policy-crd.yaml`:

```yaml
spec:
  filesystem:
    readWrite:
      - /sandbox
      - /tmp
      - /my-custom-path  # Add new writable path
```

**Note:** Filesystem and process changes require sandbox recreation.

### Provider Configuration

Edit `2-deploy/openshell-provider.yaml` to change credential management:

```yaml
spec:
  credentialsSecretRef:
    name: my-secret
    keys:
      - API_KEY
```

### Namespace and Images

Edit `2-deploy/kustomization.yaml` to change the target namespace or override image references.

## Monitoring

### View All OpenShell Resources

```bash
oc get openshellpolicy,openshellprovider,openshellsandbox -n ${NAMESPACE}
```

### Check Policy Enforcement

```bash
# View applied policy hash
oc get openshellsandbox opencode-dual -n ${NAMESPACE} -o yaml | grep appliedPolicyHash

# Check policy status
oc describe openshellpolicy vuln-agent-policy -n ${NAMESPACE}
```

### View Sandbox Logs

```bash
# Find the sandbox pod (format: default--<sandbox-name>)
oc logs -f default--opencode-dual -n ${NAMESPACE}
```

### Check Operator Logs

```bash
oc logs -n openshell-operator-system deployment/openshell-operator -f
```

## Troubleshooting

### Provider shows "SecretNotEntitled" error

**Symptom:**
```
Warning  SecretNotEntitled  secret is not entitled for provider references
```

**Fix:**
The updated `setup-operator.sh` automatically adds the required annotation, but if needed manually:

```bash
oc annotate secret opencode-api-keys -n ${NAMESPACE} \
  openshell.lenshq.io/allow-provider-ref=true --overwrite
```

### Sandbox not ready

```bash
# Check sandbox status
oc describe openshellsandbox opencode-dual -n ${NAMESPACE}

# Check events
oc get events -n ${NAMESPACE} --sort-by='.lastTimestamp' | tail -20
```

### Operator pod issues

```bash
# Check operator pod
oc get pods -n openshell-operator-system

# View logs
oc logs -n openshell-operator-system -l app.kubernetes.io/name=openshell-operator
```

## Teardown

```bash
source env.sh
./2-deploy/teardown.sh
```

This removes:
- OpenShell CRDs (sandbox, provider, policy)
- Sandbox pod
- Gateway
- Secrets
- Namespace
- SCC

**Note:** The operator itself remains installed (cluster-wide). To uninstall:

```bash
helm uninstall openshell-operator -n openshell-operator-system
oc delete namespace openshell-operator-system
```

## Legacy Approach

The legacy CLI-based approach (`setup.sh`) is still available but **not recommended**:

```bash
# ⚠️  WARNING: Policy not enforced with this approach
./2-deploy/setup.sh
```

Use `setup-operator.sh` for proper policy enforcement.

## Additional Documentation

- [DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md) - Complete deployment guide
- [OPERATOR-MIGRATION.md](./OPERATOR-MIGRATION.md) - CLI vs Operator comparison
- [POLICY-ENFORCEMENT-EXPLAINED.md](./POLICY-ENFORCEMENT-EXPLAINED.md) - How policies work
- [INSTALL-OPERATOR.md](./INSTALL-OPERATOR.md) - Operator installation details

## Next Step

Proceed to [Phase 3: Verify](../3-demo/README.md) to test your deployment.
