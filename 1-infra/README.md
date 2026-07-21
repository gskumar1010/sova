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
