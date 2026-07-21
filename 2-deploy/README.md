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
