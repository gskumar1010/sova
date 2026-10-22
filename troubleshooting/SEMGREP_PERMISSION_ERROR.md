# Semgrep Permission Error - Agent Produces No Output

## Symptom

```
Agent completed: exit_code=0, stdout_len=0, stderr_len=40
STDERR: [0m> build · nemotron-30b-vulkan[0m
```

The agent exits successfully but produces **zero output**. The scan appears to complete but no SARIF results are generated.

## Root Cause

**Two issues preventing scans:**

### 1. Semgrep Permission Error
```
PermissionError: [Errno 13] Permission denied: '/.semgrep'
```

**Cause:** The sandbox pod has `HOME=/` (root filesystem) which is read-only. Semgrep tries to create `/.semgrep/settings.yml` and fails.

**Impact:** Semgrep crashes before scanning, producing no output.

### 2. Missing Files in /sandbox/
```bash
ls /sandbox/vuln_scan.py
# File not found
```

**Cause:** The startup.sh script that stages files from the image (`/home/user/workspace/`) to the sandbox workspace (`/sandbox/`) is not running automatically on pod startup.

**Impact:** The OpenCode agent has no scanning tools available, so it does nothing.

## Diagnosis Commands

### Check if files are staged
```bash
oc exec default--opencode-dual -n openshell-kata -- ls -la /sandbox/ | grep vuln_scan
# Expected: -rwxr-xr-x vuln_scan.py
# Actual: (no output) = FILE MISSING
```

### Check HOME environment variable
```bash
oc exec default--opencode-dual -n openshell-kata -- env | grep HOME
# Current: HOME=/
# Expected: HOME=/sandbox
```

### Test semgrep manually
```bash
oc exec default--opencode-dual -n openshell-kata -- /opt/scantools/bin/semgrep --version
# Error: PermissionError: [Errno 13] Permission denied: '/.semgrep'
```

### Test with proper environment
```bash
oc exec default--opencode-dual -n openshell-kata -- sh -c 'export HOME=/sandbox && /opt/scantools/bin/semgrep --version'
# Works: 1.85.0
```

## Fix

### Short-term: Manual File Staging (Immediate)

Run this after sandbox starts:
```bash
oc exec default--opencode-dual -n openshell-kata -- /usr/local/bin/startup.sh echo "done"
```

This stages:
- `/sandbox/vuln_scan.py`
- `/sandbox/code_graph.py`
- `/sandbox/SECURITY_ANALYST.md`
- `/sandbox/.agents/security-analyst.md`

### Long-term: Update OpenShellSandbox Manifest

**File:** `2-deploy/openshell-sandbox.yaml`

Add `HOME` and `SEMGREP_SETTINGS_FILE` to environment variables:

```yaml
environment:
  OPENAI_BASE_URL: "MODEL_ENDPOINT_PLACEHOLDER/v1"
  OPENAI_API_KEY: "API_KEY_PLACEHOLDER"
  OPENCODE_DISABLE_MODELS_FETCH: "1"
  OPENCODE_DISABLE_AUTOUPDATE: "1"
  OPENCODE_PURE: "1"
  OPENCODE_DISABLE_LSP_DOWNLOAD: "1"
  OPENCODE_DB: ":memory:"
  OPENCODE_CONFIG: "/sandbox/.config/opencode/config.json"
  VULN_API_URL: "VULN_API_URL_PLACEHOLDER"
  HOME: "/sandbox"  # <-- ADD THIS
  SEMGREP_SETTINGS_FILE: "/sandbox/.semgrep/settings.yml"  # <-- ADD THIS
```

**Apply the fix:**
```bash
# Update manifest locally
git pull origin main

# Delete existing sandbox
oc delete openshellsandbox opencode-dual -n openshell-kata

# Apply updated manifest
oc apply -k 2-deploy/

# Wait for Ready
oc get openshellsandbox opencode-dual -n openshell-kata -w
```

## Verification

### 1. Check HOME is set correctly
```bash
oc exec default--opencode-dual -n openshell-kata -- env | grep HOME
# Expected: HOME=/sandbox
```

### 2. Check files are staged
```bash
oc exec default--opencode-dual -n openshell-kata -- ls -la /sandbox/ | grep -E "(vuln_scan|SECURITY)"
# Expected:
# -rwxr-xr-x vuln_scan.py
# -rwxr-xr-x SECURITY_ANALYST.md
```

### 3. Test semgrep works
```bash
oc exec default--opencode-dual -n openshell-kata -- /opt/scantools/bin/semgrep --version
# Expected: 1.85.0 (no errors)
```

### 4. Run a test scan via UI
- Submit a small repo: `https://github.com/OWASP/NodeGoat.git`
- Should complete in ~45 seconds
- Should produce SARIF output with findings

## Why This Happened

The OpenShell operator does NOT preserve the ENTRYPOINT from the Dockerfile when creating sandbox pods. The `images/agent-sandbox/Dockerfile` specifies:

```dockerfile
ENTRYPOINT ["/usr/local/bin/startup.sh"]
```

But OpenShell overrides this with its own entrypoint, so `startup.sh` never runs automatically.

**Workarounds:**
1. Run startup.sh manually after pod creation (short-term)
2. Set `HOME=/sandbox` in environment variables (permanent fix)
3. Consider using an init-container to stage files (future enhancement)

## Related Issues

- **TIMEOUT_TROUBLESHOOTING.md**: Documents network policy timeouts (different issue)
- **DNS_KATA_ISSUE.md**: Documents Kata VM DNS resolution (different issue)

## Prevention

Before deploying a new sandbox:
- [ ] Verify `HOME=/sandbox` in `openshell-sandbox.yaml`
- [ ] Verify `SEMGREP_SETTINGS_FILE` set in environment
- [ ] Test file staging: `oc exec ... -- ls /sandbox/vuln_scan.py`
- [ ] Test semgrep: `oc exec ... -- /opt/scantools/bin/semgrep --version`
- [ ] Run test scan with NodeGoat before production use
