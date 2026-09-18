# How OpenShell Network Policies Get Enforced in Pods

This document explains the complete flow of how OpenShell network policies go from Kubernetes CRDs to actual enforcement inside your pods on OpenShift.

## 🔄 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. KUBERNETES CRD (Declarative Policy Definition)                       │
│                                                                          │
│  apiVersion: openshell.lenshq.io/v1alpha1                               │
│  kind: OpenShellPolicy                                                  │
│  metadata:                                                              │
│    name: vuln-agent-policy                                              │
│  spec:                                                                  │
│    networkPolicies:                                                     │
│      model_inference:                                                   │
│        endpoints:                                                       │
│          - host: maas-rhdp.apps.maas.redhatworkshops.io                │
│            port: 8000                                                   │
│            enforcement: enforce                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ ① Operator watches CRD
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. OPENSHELL OPERATOR (Reconciliation Loop)                            │
│    Namespace: openshell-operator-system                                 │
│                                                                          │
│  • Watches OpenShellPolicy, OpenShellProvider, OpenShellSandbox CRDs    │
│  • Reads policy document from Kubernetes                                │
│  • Validates policy schema                                              │
│  • Sends policy to gateway via gRPC                                     │
│                                                                          │
│  Log: "reconciling OpenShellSandbox name=opencode-dual"                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ ② gRPC call with policy
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. OPENSHELL GATEWAY (Central Policy Manager)                          │
│    Pod: openshell-kata-0                                                │
│                                                                          │
│  • Receives policy via gRPC from operator                               │
│  • Stores policy in gateway database                                    │
│  • Assigns policy hash: 642e5d6818b27cea                                │
│  • When sandbox is created, injects policy into pod                     │
│  • Provides JWT tokens for sandbox authentication                       │
│                                                                          │
│  Endpoint: http://openshell-kata.openshell-kata.svc:8080               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ ③ Pod creation with policy
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. SANDBOX POD (default--opencode-dual)                                │
│    RuntimeClass: kata (VM isolation)                                    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Init Container: openshell-supervisor-install                     │   │
│  │  • Runs: ghcr.io/nvidia/openshell/supervisor:0.0.116            │   │
│  │  • Copies /openshell-sandbox binary to shared volume             │   │
│  │  • Exits after copy completes                                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    │ Binary copied to /opt/openshell/    │
│                                    ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Main Container: agent                                            │   │
│  │  PID 1: /opt/openshell/bin/openshell-sandbox --workdir /sandbox │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────┐     │   │
│  │  │ OPENSHELL SUPERVISOR PROCESS (PID 1)                   │     │   │
│  │  │  • Runs as root (PID 1 in container)                   │     │   │
│  │  │  • Fetches policy from gateway using JWT token         │     │   │
│  │  │  • Sets up enforcement mechanisms:                     │     │   │
│  │  │    - Landlock LSM for filesystem                       │     │   │
│  │  │    - eBPF/nftables for network filtering               │     │   │
│  │  │    - Seccomp for syscall filtering                     │     │   │
│  │  │  • Spawns child processes as 'sandbox' user           │     │   │
│  │  └────────────────────────────────────────────────────────┘     │   │
│  │                         │                                        │   │
│  │                         │ ④ Spawns child with restrictions       │   │
│  │                         ▼                                        │   │
│  │  ┌────────────────────────────────────────────────────────┐     │   │
│  │  │ YOUR WORKLOAD (PID 19)                                 │     │   │
│  │  │  User: sandbox                                         │     │   │
│  │  │  Command: sleep infinity (or your agent)               │     │   │
│  │  │                                                        │     │   │
│  │  │  🔒 ENFORCEMENTS ACTIVE:                              │     │   │
│  │  │  • Filesystem: Only /sandbox, /tmp, /home writable    │     │   │
│  │  │  • Network: Only allowed endpoints reachable          │     │   │
│  │  │  • Process: Running as sandbox user                   │     │   │
│  │  └────────────────────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

## 📋 Step-by-Step Breakdown

### Step 1: You Create a CRD

```bash
oc apply -f openshell-policy-crd.yaml
```

This creates an `OpenShellPolicy` object in Kubernetes. It's **just metadata** at this point - not enforced yet.

### Step 2: Operator Reconciles

The OpenShell Operator (running in `openshell-operator-system`) watches for CRD changes:

```rust
// Simplified operator logic
INFO reconciling OpenShellPolicy name=vuln-agent-policy
  → Read policy document from Kubernetes
  → Validate schema
  → Call gateway.SyncPolicy(policy_document) via gRPC
```

**Evidence in your cluster:**
```bash
oc logs -n openshell-operator-system deployment/openshell-operator
# Output: "reconciling object OpenShellPolicy..."
```

### Step 3: Gateway Stores Policy

The gateway receives the policy and stores it:

```
Gateway Database:
  policy_id: vuln-agent-policy
  hash: 642e5d6818b27cea  ← This is proof it was received!
  document: {filesystem: ..., networkPolicies: ...}
```

When a sandbox references `policyRef: vuln-agent-policy`, the gateway looks it up by name.

### Step 4: Pod Creation with Policy Injection

When the `OpenShellSandbox` is created:

1. **Gateway creates the pod** with special init container and command
2. **Init container** copies the `openshell-sandbox` supervisor binary
3. **Main container** runs with the supervisor as PID 1
4. **Supervisor** fetches policy from gateway and applies it

**Pod structure (what you see):**
```bash
oc describe pod default--opencode-dual -n openshell-kata

Init Containers:
  openshell-supervisor-install:
    Image: ghcr.io/nvidia/openshell/supervisor:0.0.116
    Command: /openshell-sandbox copy-self /opt/openshell/bin/openshell-sandbox

Containers:
  agent:
    Command: /opt/openshell/bin/openshell-sandbox --workdir /sandbox
```

### Step 5: Runtime Enforcement

**Inside the pod**, the supervisor enforces policies using Linux kernel features:

#### A. Filesystem Policy (via Landlock LSM)

```c
// Supervisor sets up Landlock rules
landlock_ruleset_create()
landlock_add_rule(LANDLOCK_ACCESS_FS_READ_DIR, "/usr")     // Read-only
landlock_add_rule(LANDLOCK_ACCESS_FS_WRITE_FILE, "/sandbox") // Read-write
landlock_restrict_self()  // Apply to all child processes
```

**Result:** Your workload can only write to `/sandbox`, `/tmp`, `/home` as defined in the policy.

#### B. Network Policy (via eBPF + Egress Proxy)

The supervisor sets up network filtering:

```
┌─────────────────────────────────────────────────────────┐
│ Your Process (PID 19)                                    │
│   → curl https://maas-rhdp.apps.maas.redhatworkshops.io │
└─────────────────────────────────────────────────────────┘
                        │
                        │ ① Outbound connection
                        ▼
┌─────────────────────────────────────────────────────────┐
│ OpenShell Supervisor eBPF Filter                         │
│   • Checks destination against policy                    │
│   • Checks calling binary path (/usr/bin/curl)          │
│   • maas-rhdp.apps.maas.redhatworkshops.io:8000 → ALLOW │
│   • github.com:443 → ALLOW (git_hosting policy)         │
│   • random-site.com → DENY                               │
└─────────────────────────────────────────────────────────┘
```

**Policy lookup:**
```yaml
networkPolicies:
  model_inference:
    endpoints:
      - host: maas-rhdp.apps.maas.redhatworkshops.io  # ✅ ALLOWED
        port: 8000
    binaries:
      - path: /usr/bin/curl  # ✅ curl can access this
```

#### C. Process Restrictions

```bash
# Inside pod
ps aux
# USER    PID  COMMAND
# root      1  /opt/openshell/bin/openshell-sandbox  ← Supervisor (enforcer)
# sandbox  19  sleep infinity                         ← Your workload (restricted)
```

The supervisor:
1. Runs as `root` (needs privileges to set up enforcement)
2. Spawns your workload as `sandbox` user (unprivileged)
3. Workload cannot escalate privileges due to seccomp filters

## 🔍 Verification: How to Prove Policy is Enforced

### 1. Check Policy Hash

```bash
oc get openshellsandbox opencode-dual -n openshell-kata -o yaml | grep appliedPolicyHash

# Output:
# appliedPolicyHash: 642e5d6818b27cea  ← Policy WAS applied!
```

### 2. Test Filesystem Restrictions

```bash
# Try to write outside allowed paths
oc exec default--opencode-dual -n openshell-kata -- touch /usr/test.txt
# Expected: Permission denied (Landlock blocking)

# Write to allowed path
oc exec default--opencode-dual -n openshell-kata -- touch /sandbox/test.txt
# Expected: Success
```

### 3. Test Network Restrictions

```bash
# Allowed endpoint (model)
oc exec default--opencode-dual -n openshell-kata -- curl -I https://maas-rhdp.apps.maas.redhatworkshops.io
# Expected: Success (200 OK)

# Disallowed endpoint
oc exec default--opencode-dual -n openshell-kata -- curl -I https://evil-site.com
# Expected: Timeout or connection refused (eBPF blocking)
```

### 4. Check Supervisor is Running

```bash
oc exec default--opencode-dual -n openshell-kata -- ps aux | grep openshell

# Output:
# root  1  /opt/openshell/bin/openshell-sandbox --workdir /sandbox
#        ↑ PID 1 = Supervisor is the enforcer
```

## 🔄 Hot-Reload: How Runtime Updates Work

When you edit the policy:

```bash
oc edit openshellpolicy vuln-agent-policy -n openshell-kata
```

**Flow:**
1. Kubernetes updates the CRD
2. Operator detects change → reconciles
3. Operator sends updated policy to gateway via gRPC
4. Gateway pushes update to **running** sandbox pods
5. Supervisor receives new policy via push notification
6. **Network policies** are updated in-place (eBPF rules updated)
7. **Filesystem/process policies** require pod restart (immutable)

**Evidence:**
```bash
# Watch policy hash change
oc get openshellsandbox opencode-dual -n openshell-kata -o yaml | grep appliedPolicyHash
# Before: appliedPolicyHash: 642e5d6818b27cea
# After:  appliedPolicyHash: 123abc456def789  ← New hash!
```

## 🆚 Comparison with Kubernetes NetworkPolicy

| Feature | Kubernetes NetworkPolicy | OpenShell Network Policy |
|---------|-------------------------|-------------------------|
| **Scope** | Pod-to-pod within cluster | Egress to external endpoints |
| **Granularity** | Pod/namespace labels | L7 endpoints + binary paths |
| **Implementation** | CNI plugin (Calico/OVN) | eBPF in sandbox supervisor |
| **Enforcement Point** | Network layer (L3/L4) | Application layer (L7) |
| **Binary-aware** | ❌ No | ✅ Yes - checks calling process |

**Example:** OpenShell can enforce:
```yaml
# Only curl can access github.com, not python scripts
networkPolicies:
  git_hosting:
    endpoints:
      - host: github.com
    binaries:
      - path: /usr/bin/git   # ✅ Allowed
      - path: /usr/bin/curl  # ✅ Allowed
# /usr/bin/python3 → github.com = ❌ DENIED
```

Kubernetes NetworkPolicy cannot do this!

## 🔐 Security Layers

Your deployment has **multiple** security layers:

```
Layer 1: Kata Containers (VM isolation)
  ↓ Strongest boundary - separate kernel
Layer 2: OpenShell Supervisor (PID 1)
  ↓ Policy enforcement via Landlock/eBPF
Layer 3: Workload (sandbox user)
  ↓ Unprivileged, restricted
```

All three must be bypassed for an escape!

## 📊 Summary

**Q: Where does the policy actually run?**
**A:** Inside each sandbox pod, enforced by the `openshell-sandbox` supervisor process running as PID 1.

**Q: How does it get there?**
**A:**
1. Operator reads CRD from Kubernetes
2. Operator sends to gateway via gRPC
3. Gateway stores and serves to pods
4. Supervisor fetches and enforces at runtime

**Q: What if I delete the OpenShellPolicy CRD?**
**A:** Running sandboxes keep their last-applied policy. New sandboxes without a policy will use the gateway's default policy.

**Q: Can I bypass the policy?**
**A:** No - it's enforced by the kernel (Landlock LSM, eBPF, seccomp) at the supervisor level. Even `root` inside the container cannot escape without also breaking out of the Kata VM.

---

**Key Takeaway:** The policy flows from Kubernetes CRD → Operator → Gateway → Pod Supervisor → Kernel Enforcement. The actual enforcement happens **inside the pod** via the OpenShell supervisor binary running as PID 1, using Linux kernel security features.
