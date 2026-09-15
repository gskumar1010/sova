# Phase 2: Deployment

**Audience:** Namespace admin
**Duration:** 5-10 minutes

This phase deploys the OpenShell gateway, SOVA vulnerability orchestrator API,
SOVA dashboard UI, and creates a dual-protection security analyst sandbox
(OpenShell + Kata).

## Prerequisites

- [Phase 1](../1-infra/README.md) complete (Kata installed)
- `oc` CLI logged in
- `helm` v3 installed
- `openshell` CLI installed
- Container images built and pushed:
  ```bash
  source env.sh

  # Some manual steps are needed as of now, need to revisit this
  oc create ${NAMESPACE}
  oc create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<github-pat> \
  -n ${NAMESPACE}

  # Agent sandbox with security analyst persona
  podman build --platform linux/amd64 -f images/agent-sandbox/Dockerfile \
    -t ${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest .
  podman push ${REGISTRY}/${NAMESPACE}/openshell-kata-agent-sandbox:latest

  # Vulnerability orchestrator API
  podman build --platform linux/amd64 -f images/vuln-orchestrator/Dockerfile \
    -t ${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest .
  podman push ${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest

  # SOVA dashboard UI
  podman build --platform linux/amd64 -f images/vuln-ui/Dockerfile \
    -t ${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest .
  podman push ${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest
  ```

  **Note:** The `setup.sh` script will build and push the orchestrator and UI
  images automatically unless you set `SKIP_BUILD=1`.

## Deploy

```bash
source env.sh
./2-deploy/setup.sh
```

The script:
1. Builds and pushes SOVA app images (vuln-orchestrator-api, sova-dashboard-ui)
2. Creates the namespace and SCC (`oc apply -k`)
3. Deploys the vulnerability orchestrator API
4. Deploys the SOVA dashboard UI with OpenShift Route
5. Creates the API key secret for model access
6. Installs the OpenShell gateway via Helm
7. Generates JWT signing keys
8. Creates the dual-protection security analyst sandbox (`openshell sandbox create` with Kata RuntimeClass)
9. Stages vuln_scan.py tool and SECURITY_ANALYST.md persona into sandbox workspace

## Customization

**Namespace and images:** Edit `2-deploy/kustomization.yaml` to change
the target namespace or override image references.

**Network policy:** Edit `2-deploy/openshell-policy.yaml` to allow
additional endpoints. The `MODEL_ENDPOINT_HOST` and `MODEL_ENDPOINT_PORT`
placeholders are substituted by `setup.sh` from your `env.sh`. By default,
the policy allows:
- Model inference endpoint (Gemma via OpenShift AI)
- Vulnerability orchestrator API (vuln-orchestrator-api:8080)
- Git operations for repository cloning (within sandbox)

## Teardown

```bash
source env.sh
./2-deploy/teardown.sh
```

This removes the sandbox, gateway, secrets, namespace, and SCC.
The Kata operator and KataConfig are left in place.

## Next Step

Proceed to [Phase 3: Verify](../3-demo/README.md).
