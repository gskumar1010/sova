# Vulnerability Scanner Timeout Troubleshooting

## Symptom
```
OpenCode exited with code 124
Agent timed out (exceeded 10 minute limit)
```

## Root Causes of Timeouts

### 1. **Network Policy Blocks** (MOST COMMON)
**Symptom:** Semgrep hangs indefinitely, no output
**Cause:** Binary not in network policy allowlist
**How to diagnose:**
```bash
# Check supervisor logs for DENIED messages
oc logs -n openshell-kata <supervisor-pod> | grep DENIED

# Look for:
OCSF NET:OPEN [MED] DENIED /usr/bin/python3.12(0) -> semgrep.dev:443
```

**Fix:** Add missing binary to `openshell-policy-crd.yaml`:
```yaml
scanner_dependencies:
  binaries:
    - path: /usr/bin/python3.12  # <-- Add this
```

### 2. **Large Repository Clone**
**Symptom:** Clone takes >5 minutes
**Cause:** Repository >500MB or very slow network
**How to diagnose:**
```bash
# Check clone result
/sandbox/vuln_scan.py clone --url <url> --dest /sandbox/tmp/scan
# Returns: {"size_mb": 43.01, ...}
```

**Fix:**
- Repository >500MB will be rejected automatically
- For slow networks, increase timeout in `vuln_scan.py` line 53:
  ```python
  timeout=CLONE_TIMEOUT  # Default: 300s (5 min)
  ```

### 3. **Semgrep Rule Download Failure**
**Symptom:** Semgrep starts but never produces output
**Cause:** curl cannot download rules from semgrep.dev
**How to diagnose:**
```bash
# Test rule download manually
curl -sL https://semgrep.dev/c/p/security-audit -o /tmp/test-rules.yaml
# Check file size
ls -lh /tmp/test-rules.yaml  # Should be ~460KB
```

**Fix:** Check network policy allows `/usr/bin/curl` to `semgrep.dev:443`

### 4. **Semgrep Scanning Very Large Repo**
**Symptom:** Semgrep runs but exceeds 10 minutes
**Cause:** Repository has 10,000+ files
**How to diagnose:**
```bash
# Count files in repo
find /sandbox/tmp/scan -type f | wc -l
```

**Performance benchmarks:**
- Small repo (NodeGoat, 3.8MB): ~35 seconds
- Medium repo (Juice Shop, 43MB): ~2-3 minutes (estimated)
- Large repo (Linux kernel, >1GB): Would timeout

**Fix:**
- Increase semgrep timeout in `vuln_scan.py` line 98:
  ```python
  timeout=300  # Increase to 600 for large repos
  ```
- Or exclude large directories: `--exclude=node_modules,vendor`

### 5. **Python Import Errors**
**Symptom:** Tool exits immediately with error
**Cause:** Missing pkg_resources or semgrep dependencies
**How to diagnose:**
```bash
# Test imports
/opt/scantools/bin/python3 -c "import pkg_resources; print('OK')"
/opt/scantools/bin/semgrep --version
```

**Fix:** Ensure setuptools<70 installed (provides pkg_resources)

### 6. **Disk Space Exhaustion**
**Symptom:** Clone or scan fails mid-execution
**Cause:** /sandbox volume full
**How to diagnose:**
```bash
df -h /sandbox
du -sh /sandbox/tmp/scan
```

**Fix:** Clean up old scans:
```bash
rm -rf /sandbox/tmp/scan
```

### 7. **OpenCode Auto-Update Delays**
**Symptom:** 30-60 second delay before scan starts
**Cause:** OpenCode checking npm registry for updates
**How to diagnose:**
```bash
# Check supervisor logs
oc logs <supervisor-pod> | grep npmjs
# Look for:
DENIED registry.npmjs.org
```

**Fix:** Already disabled in config (`"autoupdate": false`)

## Diagnostic Commands

### Check Current Scan Status
```bash
# From outside sandbox
oc exec -n openshell-kata deployment/sova-dashboard-ui -- python3 -c "
from openshell.sandbox import SandboxClient
client = SandboxClient(endpoint='openshell-kata:8080', tls=None, bearer_token=None, timeout=60.0)
result = client.exec(
    sandbox='opencode-dual',
    command=['ps', 'aux'],
    workspace='default',
    timeout_seconds=10,
    no_login_shell=True
)
print(result.stdout)
client.close()
"
```

### Check Network Policy Status
```bash
# Get current policy
oc get openshellpolicy vuln-agent-policy -n openshell-kata -o yaml

# Check recent policy updates
oc get openshellpolicy vuln-agent-policy -n openshell-kata -o jsonpath='{.metadata.resourceVersion}'
```

### View Real-Time Supervisor Logs
```bash
# Find supervisor pod
oc get pods -n openshell-kata | grep supervisor

# Tail logs
oc logs -n openshell-kata <supervisor-pod> -f --tail=50
```

## Expected Scan Times

| Repository | Size | Clone | Semgrep | Bandit | Total |
|-----------|------|-------|---------|--------|-------|
| NodeGoat | 3.8MB | 2s | 35s | 5s | ~45s |
| Hello-World | 0.03MB | 2s | 33s | 2s | ~40s |
| Juice Shop | 43MB | 3s | 120s* | 10s* | ~2.5min* |

*Estimated based on file count

## Prevention Checklist

Before deploying:
- [ ] All scanner binaries in network policy
- [ ] `/usr/bin/python3.12` in network policy (for semgrep)
- [ ] Curl can access semgrep.dev:443
- [ ] Test with small repo first (NodeGoat)
- [ ] Check supervisor logs for DENIED messages
- [ ] Verify setuptools version <70 (for pkg_resources)

## Quick Fix Steps

If scan times out:
1. Check supervisor logs: `oc logs <supervisor-pod> | grep DENIED`
2. Add denied binary to policy
3. Apply updated policy: `oc apply -f openshell-policy-crd.yaml`
4. Wait 30 seconds for hot-reload
5. Retry scan

## Emergency Workaround

If policy changes don't take effect:
```bash
# Recreate sandbox (forces policy reload)
oc delete openshellsandbox opencode-dual -n openshell-kata
oc apply -f 2-deploy/openshell-sandbox.yaml
# Wait for Ready status
oc get openshellsandbox opencode-dual -n openshell-kata -w
```
