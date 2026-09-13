# 2-deploy/ Directory Changes Summary

## Overview
The `2-deploy/` directory has been fully transformed from Travel Agent deployment to SOVA deployment manifests.

---

## ✅ Files Changed

### New Files Created
1. **vuln-orchestrator-api.yaml**
   - Deployment + Service for vulnerability orchestration FastAPI
   - Replaces: `mock-travel-api.yaml`
   - Image: `vuln-orchestrator-api:latest`
   - Adds volume mounts for scan data persistence

2. **sova-dashboard-ui.yaml**
   - Deployment + Service + ServiceAccount + Route for SOVA UI
   - Replaces: `travel-ui.yaml`
   - Image: `sova-dashboard-ui:latest`
   - Increased timeout to 600s for longer vulnerability scans

3. **MIGRATION_NOTES.md**
   - Comprehensive migration guide
   - Troubleshooting tips
   - Verification commands

### Files Updated

4. **openshell-policy.yaml**
   ```yaml
   # Changed:
   travel_api → vuln_orchestrator_api
   host: mock-travel-api → vuln-orchestrator-api
   # Added:
   - { path: /usr/bin/git }  # For repository cloning
   ```

5. **kustomization.yaml**
   ```yaml
   # Changed resource references:
   - mock-travel-api.yaml → vuln-orchestrator-api.yaml
   - travel-ui.yaml → sova-dashboard-ui.yaml
   ```

6. **setup.sh**
   - Image builds: Updated to build vuln-orchestrator-api and sova-dashboard-ui
   - Staging: Changed to copy vuln_scan.py + SECURITY_ANALYST.md
   - UI route: Updated to reference sova-dashboard-ui

7. **README.md**
   - Updated deployment documentation
   - Added SOVA-specific build instructions
   - Clarified network policy configuration

### Files Removed
- ❌ `mock-travel-api.yaml` - No longer needed
- ❌ `travel-ui.yaml` - No longer needed

### Files Unchanged
- `namespace.yaml` - Generic, no changes needed
- `openshell-scc.yaml` - Security context constraints unchanged
- `openshell-helm-values.yaml` - Generic Helm configuration
- `secret-api-keys.yaml.example` - Generic API key template
- `teardown.sh` - Uses kustomize, automatically picks up new resources

---

## 🔍 Key Changes Detail

### Network Egress Policy
**Before:**
```yaml
travel_api:
  endpoints:
    - host: mock-travel-api
      port: 8080
```

**After:**
```yaml
vuln_orchestrator_api:
  endpoints:
    - host: vuln-orchestrator-api
      port: 8080
  binaries:
    - { path: /usr/bin/git }  # NEW: Added for git operations
```

### Image References
| Component | Old Image | New Image |
|-----------|-----------|-----------|
| Orchestrator | `openshell-kata-mock-travel-api:latest` | `vuln-orchestrator-api:latest` |
| UI | `openshell-kata-travel-ui:latest` | `sova-dashboard-ui:latest` |
| Sandbox | `openshell-kata-agent-sandbox:latest` | `openshell-kata-agent-sandbox:latest` *(unchanged)* |

### Environment Variables
**Removed from UI:**
- `TRAVEL_UI_FAKE` - No longer needed (always live mode)

**Changed in UI:**
- `OPENSHELL_EXEC_TIMEOUT: "300"` → `"600"` (vulnerability scans need more time)

---

## 🚀 Deployment Impact

### What Changed
1. **API Service Name**: `mock-travel-api` → `vuln-orchestrator-api`
2. **UI Route Name**: `travel-ui` → `sova-dashboard-ui`
3. **Workspace Files**: `travel_search.py` + `AGENTS.md` → `vuln_scan.py` + `SECURITY_ANALYST.md`

### What Stayed the Same
1. Namespace: `openshell-kata` (configurable via env.sh)
2. OpenShell gateway configuration
3. Kata RuntimeClass setup
4. SCC (Security Context Constraints)
5. JWT signing mechanism
6. API key secret structure

---

## 📋 Deployment Checklist

When deploying SOVA:

- [ ] **Step 1**: Configure `env.sh` with your registry and model endpoint
- [ ] **Step 2**: Build agent sandbox image:
  ```bash
  podman build -f images/agent-sandbox/Dockerfile \
    -t ${REGISTRY}/openshell-kata-agent-sandbox:latest .
  podman push ${REGISTRY}/openshell-kata-agent-sandbox:latest
  ```
- [ ] **Step 3**: Run setup (builds orchestrator + UI images automatically):
  ```bash
  source env.sh
  ./2-deploy/setup.sh
  ```
- [ ] **Step 4**: Verify deployment:
  ```bash
  oc get pods -n openshell-kata
  oc get route sova-dashboard-ui -n openshell-kata
  ```

---

## 🔧 Quick Reference

### Access SOVA Dashboard
```bash
# Get the route URL
oc get route sova-dashboard-ui -n openshell-kata -o jsonpath='{.spec.host}'

# Opens: https://<route-host>
```

### Test Vulnerability Orchestrator API
```bash
# Port-forward to API
oc port-forward -n openshell-kata svc/vuln-orchestrator-api 8080:8080 &

# Health check
curl http://localhost:8080/healthz
# Expected: {"status":"ok","service":"vuln-orchestrator"}
```

### Verify Sandbox Configuration
```bash
# List sandboxes
openshell sandbox list

# Check workspace files
openshell sandbox exec -n opencode-dual -- ls -la /sandbox/
# Should see: vuln_scan.py, SECURITY_ANALYST.md
```

### View OpenShell Policy
```bash
# Get the active policy
openshell sandbox exec -n opencode-dual -- \
  cat /etc/openshell/policy.yaml
```

---

## 📚 Related Documentation

- See `MIGRATION_NOTES.md` for detailed migration guide
- See `README.md` for deployment instructions
- See `../3-demo/README.md` for verification steps
- See `../TRANSFORMATION_SUMMARY.md` for complete project changes

---

## ⚠️ Important Notes

1. **Breaking Changes**: Old travel agent deployments are not compatible
2. **Clean Migration**: Run `./teardown.sh` before deploying SOVA
3. **Image Registry**: Ensure all three images are pushed to your registry
4. **Network Policy**: The sandbox can ONLY reach vuln-orchestrator-api and model endpoint
5. **Timeouts**: Vulnerability scans can take 5-10 minutes for large repositories

---

## ✨ What's Next

After deploying with `./2-deploy/setup.sh`:

1. **Verify** with Phase 3 demo: `./3-demo/run-demo.sh`
2. **Test** by scanning a vulnerable repo (e.g., DVWA)
3. **Review** SARIF output in the dashboard
4. **Monitor** pod logs for troubleshooting:
   ```bash
   oc logs -f deployment/vuln-orchestrator-api -n openshell-kata
   oc logs -f deployment/sova-dashboard-ui -n openshell-kata
   ```
