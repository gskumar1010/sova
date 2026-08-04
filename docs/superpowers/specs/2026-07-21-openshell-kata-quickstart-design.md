# Design: Secure AI Agents with OpenShell and Kata Containers — Quickstart

**Date:** 2026-07-21
**Target level:** Level 1 (Community) in rh-ai-quickstart org
**Based on:** [openshell-sandbox-poc](https://github.com/...) (internal POC)
**Contributing guide:** [rh-ai-quickstart/ai-quickstart-contrib CONTRIBUTING.md](https://github.com/rh-ai-quickstart/ai-quickstart-contrib/blob/main/CONTRIBUTING.md)

## Overview

A reference architecture quickstart showing how to deploy AI coding agents on Red Hat OpenShift with dual-layer security: NVIDIA OpenShell (application-layer policy enforcement) and Kata Containers (hardware-enforced VM isolation). The two technologies protect against complementary threat classes that neither addresses alone.

This is a reference architecture, not a penetration testing demo. It shows the recommended deployment pattern and verifies that security boundaries are operational. The security model document explains the threat landscape and references real CVEs as case studies without shipping exploit code.

## Repository Structure

```
secure-agents-with-openshell-kata/
├── README.md                          # Org-template compliant
├── LICENSE                            # Apache 2.0 (already exists)
├── env.sh.example                     # MODEL_ENDPOINT, REGISTRY, NAMESPACE, OPENAI_API_KEY
├── .gitignore
├── docs/
│   ├── images/
│   │   └── architecture.png           # Architecture diagram
│   └── security-model.md             # Threat model, why both layers, CVE case studies
├── 1-infra/
│   ├── README.md                      # Phase 1 step-by-step instructions
│   ├── kustomization.yaml             # Resources: kata-operator.yaml, kata-runtimeclass.yaml
│   ├── kata-operator.yaml             # OpenShift Sandboxed Containers operator Subscription
│   ├── kata-runtimeclass.yaml         # KataConfig CR (triggers node prep + reboots)
│   ├── kata-veth-patch-job.yaml       # DaemonSet to patch Kata initramfs with veth module
│   ├── verify-kernel.sh               # Confirms Kata is functional on worker nodes
│   └── setup.sh                       # Orchestrates: oc apply -k, wait, veth patch, verify
├── 2-deploy/
│   ├── README.md                      # Phase 2 step-by-step instructions
│   ├── kustomization.yaml             # Resources: namespace.yaml, openshell-scc.yaml
│   │                                  # Namespace/image transformers for customization
│   ├── namespace.yaml                 # Target namespace
│   ├── openshell-scc.yaml             # SCC granting OpenShell supervisor capabilities
│   ├── openshell-helm-values.yaml     # Helm values for OpenShell gateway (not in kustomization)
│   ├── openshell-policy.yaml          # Network/filesystem policy for openshell sandbox create
│   ├── secret-api-keys.yaml.example   # Template for model API key secret
│   ├── setup.sh                       # Orchestrates: oc apply -k, Helm install, sandbox create
│   └── teardown.sh                    # Reverse of setup: sandbox delete, Helm uninstall, cleanup
├── 3-demo/
│   ├── README.md                      # Phase 3 step-by-step instructions
│   ├── run-demo.sh                    # Verifies agent functionality + security boundaries
│   └── lib/
│       ├── colors.sh                  # Terminal color definitions
│       └── utils.sh                   # Helper functions (pod_exec wrapper)
└── images/
    └── agent-sandbox/
        ├── Dockerfile                 # Based on openshell-community sandbox base image
        └── opencode.json              # OpenCode config pointing to model endpoint
```

## Design Decisions

### Reference architecture, not attack demo

The POC shipped exploit code (CVE-2026-31431 page-cache write, prompt injection payloads) to prove that dual protection works. The quickstart drops all exploit code and reframes as: here is the recommended deployment, here is why it's secure, here is how to verify the boundaries are working. The security model document provides the analytical depth.

**Rationale:** Org guidelines require quickstarts to document the use case, not ship security tooling. A reference architecture is more broadly useful — it works on any cluster with Kata support, not just clusters with a specific vulnerable kernel.

### Kustomize for declarative resources, shell scripts for orchestration

Kubernetes manifests are managed via `kustomization.yaml` and applied with `oc apply -k`. Shell scripts handle operations Kustomize cannot: Helm installs, `openshell sandbox create` CLI calls, waiting for readiness, ordering dependencies.

**Rationale:** Users can customize namespace and image references by editing `kustomization.yaml` instead of `sed`-ing YAML files. Scripts are kept for the genuinely imperative parts.

### Single pod (dual protection) instead of three comparison pods

The POC deployed three pods (kata-only, openshell-only, dual) to demonstrate by contrast. The quickstart deploys only the recommended configuration (OpenShell + Kata). The contrast is explained in documentation.

**Rationale:** A reference architecture shows the right way to do it. The security model doc explains why other configurations are insufficient.

### Model endpoint assumed external

The quickstart does not deploy vLLM or any model server. Users provide an OpenAI-compatible endpoint via `MODEL_ENDPOINT` in `env.sh`.

**Rationale:** Keeps the quickstart focused on the security architecture. Model serving is a separate concern with its own GPU/memory requirements.

## README Structure

Follows the org template from `rh-ai-quickstart/ai-quickstart-contrib CONTRIBUTING.md`:

1. **H1 title:** "Secure AI Coding Agents with OpenShell and Kata Containers on OpenShift"
2. **Short description:** (≤160 chars) "Deploy AI coding agents with defense-in-depth using NVIDIA OpenShell and Kata Containers on Red Hat OpenShift."
3. **Table of contents**
4. **Description:** 2-3 paragraphs on the business problem (AI agents need shell access, shell access creates two threat classes, dual protection covers both)
5. **See it in action:** Link to recording or sample output
6. **Architecture diagram:** `docs/images/architecture.png`
7. **Requirements:**
   - Hardware: bare-metal workers with hardware virtualization
   - Software: OpenShift 4.17+, Sandboxed Containers operator, OpenShell CLI, Helm 3.x, oc
   - Additional: OpenAI-compatible model endpoint, container registry
8. **Deploy:** Three phases linking to phase-specific READMEs
9. **Delete:** Link to teardown instructions
10. **Security model:** Summary threat matrix with link to `docs/security-model.md`
11. **References:** Links to OpenShell docs, Kata docs, OpenShift Sandboxed Containers docs
12. **Tags:** Product (Red Hat OpenShift, OpenShift Sandboxed Containers), Partner (NVIDIA), Industry (TBD), Use case (Security)

## Security Model Document (`docs/security-model.md`)

Sections:

1. **Threat model** — Two threat classes AI coding agents face: application-layer (prompt injection, data exfiltration, credential theft) and kernel-level (container escape, host filesystem access, lateral movement).

2. **Why two layers** — OpenShell operates inside the kernel trust boundary. Kata operates below the application layer. Neither covers both threat classes. Threat matrix table.

3. **OpenShell protection surface** — Network egress allowlist, Landlock filesystem paths, dropped capabilities, unprivileged user. Limitations: cannot block kernel memory corruption.

4. **Kata protection surface** — Dedicated guest kernel, hardware VM boundary, isolated virtiofs page cache, memory isolation. Limitations: does not inspect network traffic or enforce application-level policy.

5. **Case study: CVE-2026-31431** — Conceptual explanation of the algif_aead page-cache write vulnerability. Why OpenShell cannot block it (legitimate syscalls). Why Kata contains it (per-VM page cache). No exploit code.

6. **Policy configuration reference** — How to write OpenShell network policies. Annotated walkthrough of `2-deploy/openshell-policy.yaml`.

## Phase Details

### Phase 1: Infrastructure (`1-infra/`)

**Audience:** Cluster admin
**Duration:** 10-20 minutes (includes node reboots)

`kustomization.yaml` resources:
- `kata-operator.yaml` — Subscription for OpenShift Sandboxed Containers operator
- `kata-runtimeclass.yaml` — KataConfig CR

`setup.sh` flow:
1. `oc apply -k .` — install operator and KataConfig
2. Wait for operator pod ready
3. Wait for KataConfig to report all nodes ready (nodes reboot during this step)
4. `oc apply -f kata-veth-patch-job.yaml` — patch Kata initramfs with veth kernel module (required for OpenShell network namespace setup)
5. Run `verify-kernel.sh` — confirm Kata RuntimeClass exists and a test pod can run with it

**Note:** The veth patch does not survive node reboots. Must be re-applied after cluster maintenance.

### Phase 2: Deployment (`2-deploy/`)

**Audience:** Namespace admin
**Duration:** 5-10 minutes

`kustomization.yaml` resources:
- `namespace.yaml`
- `openshell-scc.yaml`

Kustomize transformers:
- `namespace` — set target namespace once
- `images` — override registry/tag for agent-sandbox image

`setup.sh` flow:
1. Source `env.sh` for configuration
2. `oc apply -k .` — create namespace and SCC
3. Create API key secret from `OPENAI_API_KEY` env var
4. `helm install openshell oci://ghcr.io/nvidia/openshell/helm-chart` with `openshell-helm-values.yaml`
5. Generate JWT keys via `openshell-gateway generate-certs`, upload as secret
6. Wait for OpenShell gateway StatefulSet ready
7. `openshell sandbox create` with:
   - `--policy openshell-policy.yaml`
   - `--image ${REGISTRY}/agent-sandbox:latest`
   - `--driver-config-json '{"kubernetes":{"pod":{"runtime_class_name":"kata"}}}'`
8. Wait for agent pod ready

`teardown.sh` flow:
1. `openshell sandbox delete` — remove the sandbox
2. `helm uninstall openshell` — remove gateway
3. Delete secrets, ConfigMaps
4. `oc delete -k .` — remove namespace and SCC

### Phase 3: Verify (`3-demo/`)

**Audience:** Anyone with access to the namespace
**Duration:** 2-3 minutes

`run-demo.sh` checks:

1. **Agent functional** — `openshell sandbox exec` to invoke OpenCode with a simple task (e.g., "create a hello world Python script"). Confirms the agent can reach the model endpoint and execute code inside the sandbox.

2. **Egress policy enforced** — `openshell sandbox exec` to run `curl http://example.com`. Expects `policy_denied` response. Confirms OpenShell network policy blocks unauthorized egress.

3. **Kata isolation active** — Verify pod spec shows `runtimeClassName: kata`. Run `cat /proc/version` inside the pod to show guest kernel (not host). Confirms VM boundary is in place.

Prints pass/fail summary for all three checks.

## Container Image

### `agent-sandbox` (`images/agent-sandbox/`)

Based on `ghcr.io/nvidia/openshell-community/sandboxes/base:latest`.

Additions:
- Python 3, pip, curl, jq, git (tools the agent needs)
- `opencode.json` — OpenCode configuration. The model endpoint is configured via the `OPENAI_API_KEY` and `MODEL_ENDPOINT` environment variables injected into the pod by `setup.sh` (from `env.sh`), not baked into the image.

Removals vs POC:
- No exploit scripts (`escape_demo.py`, `copy_fail_exp.py`)
- No attack payloads (`malicious.patch`, `task-prompt.txt`)
- No `/opt/marker.txt`

## Environment Variables (`env.sh.example`)

```bash
export REGISTRY="quay.io/yourorg"
export NAMESPACE="openshell-kata"
export MODEL_ENDPOINT="http://your-model-svc:8000"
export OPENAI_API_KEY="your-api-key"
```

## What's Ported from the POC

| POC file | Quickstart destination | Adaptation |
|---|---|---|
| `infra/kata-operator.yaml` | `1-infra/kata-operator.yaml` | As-is |
| `infra/kata-runtimeclass.yaml` | `1-infra/kata-runtimeclass.yaml` | As-is |
| `infra/kata-veth-patch-job.yaml` | `1-infra/kata-veth-patch-job.yaml` | As-is |
| `infra/verify-kernel.sh` | `1-infra/verify-kernel.sh` | As-is |
| `deploy/namespace.yaml` | `2-deploy/namespace.yaml` | As-is |
| `deploy/openshell-scc.yaml` | `2-deploy/openshell-scc.yaml` | As-is |
| `deploy/openshell-helm-values.yaml` | `2-deploy/openshell-helm-values.yaml` | As-is |
| `deploy/openshell-policy.yaml` | `2-deploy/openshell-policy.yaml` | As-is |
| `deploy/secret-api-keys.yaml.example` | `2-deploy/secret-api-keys.yaml.example` | As-is |
| `demo/setup.sh` | `2-deploy/setup.sh` | Simplified: single pod, no attacker listener, no attack ConfigMaps |
| `demo/teardown.sh` | `2-deploy/teardown.sh` | Simplified: single pod cleanup |
| `demo/lib/colors.sh` | `3-demo/lib/colors.sh` | As-is |
| `demo/lib/utils.sh` | `3-demo/lib/utils.sh` | Simplified: only dual-pod exec path |
| `demo/run-demo.sh` | `3-demo/run-demo.sh` | Rewritten: verify-focused instead of attack-focused |
| `images/agent-sandbox/Dockerfile` | `images/agent-sandbox/Dockerfile` | Stripped of exploit scripts and attack payloads |
| `images/agent-sandbox/opencode.json` | `images/agent-sandbox/opencode.json` | Model endpoint made configurable |
| `env.sh.example` | `env.sh.example` | Added MODEL_ENDPOINT, removed hardcoded vLLM address |
| `docs/security-model.md` | `docs/security-model.md` | Rewritten as analytical document, no exploit code |

## What's Dropped from the POC

| POC file | Reason |
|---|---|
| `attacks/` (entire directory) | No exploit code in reference architecture |
| `images/attacker-listener/` | No exfiltration target needed |
| `deploy/attacker-listener.yaml` | No exfiltration target needed |
| `deploy/pod-kata-only.yaml` | Single recommended config, not comparison pods |
| `demo/reset-pods.sh` | No multi-round attack demo |
| `docs/blogs/` | Blog content doesn't belong in a quickstart |
| `docs/ADR.md` | Internal POC planning doc |
| `docs/PLAN.md` | Internal POC planning doc |
| `docs/run.log` | Sample output; relevant excerpts go in demo README |
| `AGENTS.md` | POC-specific AI agent config |
| `.vale.ini` | POC-specific linting config |
| `infra/kata-veth-machineconfig.yaml` | Documented as non-working on RHCOS 9.6 with composefs |
| `infra/README.md` | Replaced by `1-infra/README.md` |

## What's New (not in POC)

| File | Purpose |
|---|---|
| `README.md` | Org-template compliant quickstart README |
| `docs/images/architecture.png` | Architecture diagram |
| `docs/security-model.md` | Threat model and security analysis (rewritten from POC's security-model.md) |
| `1-infra/README.md` | Phase 1 step-by-step instructions |
| `1-infra/kustomization.yaml` | Kustomize manifest list |
| `2-deploy/README.md` | Phase 2 step-by-step instructions |
| `2-deploy/kustomization.yaml` | Kustomize manifest list with namespace/image transformers |
| `3-demo/README.md` | Phase 3 verification instructions |
| `3-demo/run-demo.sh` | Verify-focused demo script (rewritten) |
