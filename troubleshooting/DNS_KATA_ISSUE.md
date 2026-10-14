# DNS Resolution Issue in Kata VM Sandbox

## Problem

GitHub cloning and external network access fails with:
```
fatal: unable to access 'https://github.com/...': Could not resolve host: github.com
```

## Root Cause

The OpenShell sandbox pod is configured with:
```yaml
dnsPolicy: None
dnsConfig:
  nameservers:
    - 127.0.0.53  # systemd-resolved stub
```

**Issue:** `127.0.0.53` is a systemd-resolved stub resolver that only works on the host. Inside a Kata VM (which runs in a separate guest kernel), this DNS server is not accessible.

## Diagnosis

```bash
# Check DNS config in sandbox
$ oc exec -n openshell-kata default--opencode-dual -- cat /etc/resolv.conf
nameserver 127.0.0.53
options ndots:5 timeout:2 attempts:2

# Test DNS resolution
$ oc exec -n openshell-kata default--opencode-dual -- nslookup github.com
;; communications error to 127.0.0.53#53: timed out
;; no servers could be reached
```

## Solution Options

### Option 1: Update OpenShell Operator (Recommended)

The OpenShell operator needs to use cluster DNS instead of systemd-resolved stub.

**Required change:** Patch the OpenShell operator to set:
```yaml
dnsPolicy: ClusterFirst  # Use cluster DNS
# OR
dnsConfig:
  nameservers:
    - 172.231.0.10  # OpenShift cluster DNS (get via: oc get service -n openshift-dns)
```

**Location:** This would need to be fixed in the OpenShell operator code or configuration.

### Option 2: Manual Pod Patch (Temporary)

Manually recreate the sandbox with correct DNS:

```bash
# Delete current sandbox
oc delete openshellsandbox opencode-dual -n openshell-kata

# Create patched version - BUT: OpenShellSandbox CRD doesn't expose dnsConfig
# This requires operator-level fix
```

**Status:** ❌ Not possible - OpenShellSandbox CRD doesn't expose DNS configuration

### Option 3: Workaround - Use IP Addresses

Clone repositories using IP addresses instead of DNS names.

```bash
# Get GitHub's IP
$ nslookup github.com
Server:		8.8.8.8
Address:	8.8.8.8#53

Non-authoritative answer:
Name:	github.com
Address: 140.82.121.4

# Clone using IP (doesn't work - HTTPS cert validation fails)
$ git clone https://140.82.121.4/user/repo.git
```

**Status:** ❌ Fails due to TLS certificate validation

### Option 4: Pre-download Repos (Current Workaround)

For demo purposes, pre-download repositories outside the sandbox and copy them in.

**Status:** ✅ Works but defeats the purpose of "test any GitHub repo"

## Impact on SOVA

**Current State:**
- ✅ Reachability analysis works (tested with local `/sandbox/dvwa-python`)
- ✅ Code graph builder works
- ✅ SARIF filtering works
- ❌ Cannot clone from GitHub inside sandbox
- ❌ Cannot test with arbitrary customer repositories

**Workaround for Demos:**
1. Create test repositories locally in `/sandbox/`
2. Or: Clone repos outside sandbox, copy files in
3. Or: Use the web UI to upload code archives

**Long-term Fix Required:**
Contact OpenShell/NVIDIA support to fix DNS configuration in Kata VM sandboxes.

## Verification After Fix

Once DNS is fixed, verify with:

```bash
# Should resolve successfully
oc exec -n openshell-kata default--opencode-dual -- nslookup github.com

# Should clone successfully
oc exec -n openshell-kata default--opencode-dual -- git clone https://github.com/OWASP/WebGoat.git /tmp/test
```

## References

- **OpenShift DNS Service:** `172.231.0.10` (verify with `oc get service -n openshift-dns`)
- **Kata Containers DNS Issue:** Known problem with systemd-resolved in VMs
- **OpenShell Operator:** Needs patch to set dnsPolicy: ClusterFirst or use cluster DNS IP

## Status

- **Reported:** 2026-10-14
- **Workaround:** Use local test repos
- **Permanent Fix:** Requires OpenShell operator update
- **Tracking:** See `/troubleshooting/TIMEOUT_TROUBLESHOOTING.md` for related network issues
