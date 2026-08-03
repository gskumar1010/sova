# Deploy Secure AI Travel Agents with OpenShell and Kata on OpenShift

Deploy AI agents with defense-in-depth using NVIDIA OpenShell and Kata Containers on Red Hat OpenShift.

## Table of Contents

- [Description](#description)
- [Business Use Case](#business-use-case)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Deploy](#deploy)
- [Delete](#delete)
- [Security Model](#security-model)
- [References](#references)
- [Tags](#tags)

## Description

AI coding agents need shell access to be productive - running tests,
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

## Business Use Case

This quickstart deploys a **travel booking assistant**: a chat UI where a user
asks for flights and hotels in natural language, and an AI agent assembles an
itinerary by calling a travel API. It is a stand-in for any enterprise agent
that must call external services on a user's behalf - booking, procurement,
support - where the agent handles untrusted input and executes tool calls.

The point of the quickstart is that this agent runs inside a **dual-protection
boundary**: OpenShell restricts its network egress to exactly the travel API and
the model endpoint, and Kata isolates it in a hardware VM. When a prompt
injection tries to make the agent exfiltrate data, the egress policy blocks it -
visibly, in the same UI.

![Travel agent itinerary](docs/images/ui-itinerary.png)

*A prompt-injection attempt to exfiltrate data is blocked by the OpenShell egress policy:*

![Blocked egress](docs/images/ui-blocked-egress.png)

> **Note:** The shipped UI runs in a self-contained demo mode
> (`TRAVEL_UI_FAKE=1`) so it renders real itineraries and the blocked-egress
> banner without depending on the `openshell` CLI being present in the UI image.
> The security boundary is proven end-to-end by the [Phase 3 demo](3-demo/README.md),
> which drives the real `openshell sandbox exec ... opencode run` path directly.
> Set `TRAVEL_UI_FAKE=0` in `2-deploy/travel-ui.yaml` to wire the UI to the live
> sandbox.

## Architecture

![Architecture](docs/images/architecture.png)

```mermaid
graph TB
    user["User (browser)"]
    travelui["Travel UI (Streamlit)"]

    subgraph cluster["OpenShift Cluster · Namespace: openshell-kata"]
        gw["OpenShell Gateway<br/><i>StatefulSet</i>"]
        mockapi["Mock Travel API<br/><i>FastAPI</i>"]

        subgraph kata_vm["Kata VM · hardware-isolated · guest kernel"]
            subgraph sandbox["OpenShell Sandbox"]
                agent["AI Coding Agent<br/><i>OpenCode</i>"]
                proxy["Egress Proxy<br/><i>deny-all default</i>"]
                landlock["Landlock FS Policy"]
            end
        end
    end

    model["Model Endpoint<br/><i>vLLM / OpenShift AI</i>"]
    blocked["Blocked"]

    user -.-> travelui
    travelui --> gw
    gw -- "lifecycle + policy" --> sandbox
    agent --> proxy
    proxy -- "allowed" --> model
    proxy -- "allowed" --> mockapi
    proxy -. "denied" .-> blocked

    style kata_vm fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style sandbox fill:#fff3e0,stroke:#ef6c00,stroke-width:2px
    style cluster fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style blocked fill:#ffcdd2,stroke:#c62828,color:#c62828
    style model fill:#f3e5f5,stroke:#7b1fa2
    style travelui fill:#e0f7fa,stroke:#00838f
    style mockapi fill:#f3e5f5,stroke:#7b1fa2
```

**Components:**

- **Kata VM** (green) - Each agent pod runs inside a lightweight VM with
  its own guest kernel, enforced by CPU virtualization (VT-x/AMD-V).
  Kernel exploits stay contained within the VM boundary.
- **OpenShell Sandbox** (orange) - The agent runs under an egress proxy
  (deny-all default; only the model endpoint and the travel API are
  allowed) and Landlock filesystem policy (kernel-enforced path
  restrictions).
- **OpenShell Gateway** - StatefulSet managing sandbox lifecycle, policy
  distribution, and JWT authentication.
- **Travel UI** - A Streamlit chat app, exposed via an OpenShift Route,
  that sends user prompts to the agent through the gateway. It is a thin
  presentation client and sits outside the security boundary.
- **Mock Travel API** - A FastAPI service returning canned flights and
  hotels. It is the one business endpoint the agent is allowed to call.
- **External Model Endpoint** - Any OpenAI-compatible service (vLLM,
  OpenShift AI). Not deployed by this quickstart.

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

- An **OpenAI-compatible model endpoint**. We recommend an open-weight model
  such as **IBM Granite** served via **Red Hat OpenShift AI** (vLLM); any
  OpenAI-compatible endpoint works. Set it in `env.sh` as `MODEL_ENDPOINT`.
- A **container image registry** you can push to (e.g., Quay.io)

## Deploy

### Prerequisites

1. Copy and configure environment variables:
   ```bash
   cp env.sh.example env.sh
   # Edit env.sh with your values
   source env.sh
   ```

2. Build and push the images (the sandbox image; `setup.sh` also builds the
   mock travel API and travel UI images):
   ```bash
   podman build -f images/agent-sandbox/Dockerfile \
     -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .
   podman push ${REGISTRY}/openshell-kata-agent-sandbox:latest
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

## Delete

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
- **Industry:** Travel and Transportation
- **Use case:** Security
