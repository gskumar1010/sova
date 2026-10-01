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
- `podman` installed (for image builds in Phase 2)

### Initial Setup

Before starting Phase 1, configure your environment:

```bash
# 1. Clone repository and configure environment variables
git clone https://github.com/gskumar1010/sova.git
cd sova
cp env.sh.example env.sh
# Edit env.sh: Set MODEL_ENDPOINT and OPENAI_API_KEY

# 2. Login to your OpenShift cluster
oc login <your-cluster-api-url>

# 3. Enable the internal image registry route (required for Phase 2 image builds)
oc patch configs.imageregistry.operator.openshift.io/cluster \
  --patch '{"spec":{"defaultRoute":true}}' --type=merge

# 4. Login to the internal registry with podman
export REGISTRY=$(oc get route default-route -n openshift-image-registry \
  -o jsonpath='{.spec.host}')
podman login -u $(oc whoami) -p $(oc whoami -t) ${REGISTRY} --tls-verify=false
```

## Deploy

### Option A: Automated (recommended)

```bash
./1-infra/setup.sh
```

The script applies all manifests, waits for readiness, patches the
initramfs, and runs verification.

**Note:** If the script fails with "subscription not found", the operator may need
a few seconds to initialize. Wait 20 seconds and rerun:

```bash
# If setup.sh fails, wait and retry
sleep 20
./1-infra/setup.sh
```

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
