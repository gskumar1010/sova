# 2-deploy/ Migration Notes: Travel Agent → SOVA

This document details the changes made to the deployment manifests for the SOVA transformation.

## File Changes Summary

### Removed Files
- ❌ `mock-travel-api.yaml` → Replaced by `vuln-orchestrator-api.yaml`
- ❌ `travel-ui.yaml` → Replaced by `sova-dashboard-ui.yaml`

### New Files
- ✅ `vuln-orchestrator-api.yaml` - Vulnerability orchestration API
- ✅ `sova-dashboard-ui.yaml` - SOVA dashboard UI

### Updated Files
- ✅ `openshell-policy.yaml` - Network egress policy
- ✅ `kustomization.yaml` - Resource references
- ✅ `setup.sh` - Build and deployment script
- ✅ `README.md` - Deployment documentation

---

## Detailed Changes

### 1. vuln-orchestrator-api.yaml (NEW)

**Purpose:** Deploys the vulnerability orchestrator FastAPI service

**Key differences from mock-travel-api.yaml:**
- Image: `vuln-orchestrator-api:latest` (was `openshell-kata-mock-travel-api:latest`)
- Added volume mounts for persistent scan data and SQLite database
- Exposes port 8080 for API access
- Health check via `/healthz` endpoint

**Volumes:**
```yaml
volumes:
  - name: scan-data
    emptyDir: {}  # Stores SARIF results
  - name: scan-db
    emptyDir: {}  # Stores SQLite database
```

### 2. sova-dashboard-ui.yaml (NEW)

**Purpose:** Deploys the SOVA vulnerability dashboard UI

**Key differences from travel-ui.yaml:**
- Image: `sova-dashboard-ui:latest` (was `openshell-kata-travel-ui:latest`)
- Removed: `TRAVEL_UI_FAKE` environment variable (always live mode)
- Changed: `OPENSHELL_EXEC_TIMEOUT` from 300s to 600s (vulnerability scans take longer)
- Route name: `sova-dashboard-ui` (was `travel-ui`)
- ServiceAccount name: `sova-dashboard-ui` (was `travel-ui`)

### 3. openshell-policy.yaml (UPDATED)

**Purpose:** Defines network egress allowlist and filesystem policies

**Changes:**
```diff
- travel_api:
-   name: travel-api
+ vuln_orchestrator_api:
+   name: vuln-orchestrator-api
    endpoints:
-     - host: mock-travel-api
+     - host: vuln-orchestrator-api
        port: 8080
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3 }
-     # travel_search.py
+     # vuln_scan.py
      - { path: /sandbox/.venv/bin/python3 }
+     # Git for repository cloning
+     - { path: /usr/bin/git }
```

**Network Policy Impact:**
- Agent can now reach: `vuln-orchestrator-api:8080`
- Agent cannot reach: `mock-travel-api:8080` (removed)
- Added git binary to allowed binaries for repository cloning

### 4. kustomization.yaml (UPDATED)

**Changes:**
```diff
resources:
  - namespace.yaml
  - openshell-scc.yaml
- - mock-travel-api.yaml
- - travel-ui.yaml
+ - vuln-orchestrator-api.yaml
+ - sova-dashboard-ui.yaml
```

### 5. setup.sh (UPDATED)

**Image Build Changes:**
```diff
- podman build -f images/mock-travel-api/Dockerfile \
-   -t "${REGISTRY}/${NAMESPACE}/openshell-kata-mock-travel-api:latest" .
+ podman build -f images/vuln-orchestrator/Dockerfile \
+   -t "${REGISTRY}/${NAMESPACE}/vuln-orchestrator-api:latest" .

- podman build -f images/travel-ui/Dockerfile \
-   -t "${REGISTRY}/${NAMESPACE}/openshell-kata-travel-ui:latest" .
+ podman build -f images/vuln-ui/Dockerfile \
+   -t "${REGISTRY}/${NAMESPACE}/sova-dashboard-ui:latest" .
```

**Workspace Staging Changes:**
```diff
- sh -c 'cp -f /home/user/workspace/travel_search.py /home/user/workspace/AGENTS.md /sandbox/'
+ sh -c 'cp -f /home/user/workspace/vuln_scan.py /home/user/workspace/SECURITY_ANALYST.md /sandbox/'
```

**UI Route Detection Changes:**
```diff
- oc get route travel-ui
+ oc get route sova-dashboard-ui

- info "Travel UI: https://${UI_HOST}"
+ info "SOVA Dashboard UI: https://${UI_HOST}"
```

### 6. README.md (UPDATED)

**Documentation Updates:**
- Phase description updated to mention SOVA components
- Image build instructions now list all three images:
  - agent-sandbox (security analyst persona)
  - vuln-orchestrator-api
  - sova-dashboard-ui
- Deployment steps updated to reflect new workflow
- Network policy documentation clarified

---

## Deployment Workflow

### Before (Travel Agent)
```
setup.sh:
1. Build mock-travel-api image
2. Build travel-ui image
3. Apply kustomize (namespace, SCC, mock-travel-api, travel-ui)
4. Install OpenShell gateway
5. Create sandbox with travel_search.py + AGENTS.md
6. Access at https://travel-ui-route
```

### After (SOVA)
```
setup.sh:
1. Build vuln-orchestrator-api image
2. Build sova-dashboard-ui image
3. Apply kustomize (namespace, SCC, vuln-orchestrator-api, sova-dashboard-ui)
4. Install OpenShell gateway
5. Create sandbox with vuln_scan.py + SECURITY_ANALYST.md
6. Access at https://sova-dashboard-ui-route
```

---

## Compatibility Notes

### Backward Incompatible Changes
- Old travel agent deployments will not work with new manifests
- Network policy no longer allows `mock-travel-api:8080`
- UI environment variable `TRAVEL_UI_FAKE` removed

### Migration Path
If you have an existing travel agent deployment:
1. Run `./2-deploy/teardown.sh` to clean up old resources
2. Update `env.sh` with your configuration
3. Run `./2-deploy/setup.sh` to deploy SOVA

### No Migration Needed For
- Namespace configuration
- SCC (Security Context Constraints)
- OpenShell Helm values
- JWT signing keys
- API key secrets

---

## Verification Commands

After deployment, verify with:

```bash
# Check all pods are running
oc get pods -n openshell-kata

# Verify vulnerability orchestrator API
oc get deployment vuln-orchestrator-api -n openshell-kata
oc get svc vuln-orchestrator-api -n openshell-kata

# Verify SOVA dashboard UI
oc get deployment sova-dashboard-ui -n openshell-kata
oc get route sova-dashboard-ui -n openshell-kata

# Check OpenShell sandbox
openshell sandbox list

# Test API health
oc port-forward -n openshell-kata svc/vuln-orchestrator-api 8080:8080 &
curl http://localhost:8080/healthz
# Expected: {"status":"ok","service":"vuln-orchestrator"}
```

---

## Troubleshooting

### Issue: vuln-orchestrator-api pod not starting
**Check:** Image pull errors
```bash
oc describe pod -l app.kubernetes.io/name=vuln-orchestrator-api -n openshell-kata
```

**Solution:** Verify image was pushed to registry
```bash
podman images | grep vuln-orchestrator-api
```

### Issue: SOVA dashboard UI shows "Sandbox not found"
**Check:** OpenShell sandbox status
```bash
openshell sandbox list
```

**Solution:** Ensure sandbox is running and named `opencode-dual`

### Issue: Agent cannot reach vuln-orchestrator-api
**Check:** Network policy applied correctly
```bash
# Exec into sandbox and test connectivity
openshell sandbox exec -n opencode-dual -- curl -v http://vuln-orchestrator-api:8080/healthz
```

**Solution:** Verify `openshell-policy.yaml` has correct endpoint

### Issue: Staging files not found in sandbox
**Check:** Files copied to /sandbox/
```bash
openshell sandbox exec -n opencode-dual -- ls -la /sandbox/
```

**Solution:** Manually stage files
```bash
openshell sandbox exec -n opencode-dual -- \
  sh -c 'cp /home/user/workspace/vuln_scan.py /home/user/workspace/SECURITY_ANALYST.md /sandbox/'
```

---

## Next Steps

After successful deployment:
1. Access SOVA dashboard at the Route URL
2. Run Phase 3 demo: `./3-demo/run-demo.sh`
3. Test with a vulnerable repository (e.g., DVWA)
4. Review SARIF output in dashboard
