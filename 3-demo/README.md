# Phase 3: Verification

**Audience:** Anyone with namespace access
**Duration:** 2-3 minutes

This phase verifies that the dual-protection sandbox is correctly
configured and operational.

## Prerequisites

- [Phase 2](../2-deploy/README.md) complete (sandbox deployed)
- `env.sh` sourced

## Run

```bash
source env.sh
./3-demo/run-demo.sh
```

## What It Checks

| Check | What it verifies | Expected result |
|-------|-----------------|-----------------|
| Vulnerability scanning | Detects vulnerabilities via SOVA orchestrator API | Vulnerability report with CWE/SARIF findings |
| Prompt-injection exfiltration | Blocked by OpenShell | `policy_denied` or connection refused |
| Kata isolation | Pod runs in a VM with a separate kernel | Guest kernel differs from host kernel |

## Expected Output

```
══════════════════════════════════════════════════════════════
  OpenShell + Kata Verification
══════════════════════════════════════════════════════════════

--- Preflight ---
  [PASS] Sandbox pod 'opencode-dual' is running
  [PASS] Pod RuntimeClass: kata

--- Check 1: Vulnerability Scanning (happy path) ---
  [PASS] Agent successfully detected vulnerabilities in test repository

--- Check 2: Prompt-injection exfiltration is blocked ---
  [PASS] Exfiltration attempt BLOCKED by OpenShell policy

--- Check 3: Kata VM Isolation ---
  [PASS] Guest kernel differs from host - Kata VM boundary confirmed

══════════════════════════════════════════════════════════════
  Results
══════════════════════════════════════════════════════════════
  Checks passed: 3/3
  All checks passed. Dual protection is operational.
```

## Test Repositories

Sample vulnerable repositories for testing SOVA:

| Repository | Language | Known Vulnerabilities |
|-----------|----------|----------------------|
| [DVWA](https://github.com/digininja/DVWA) | PHP | SQL Injection (CWE-89), XSS (CWE-79), CSRF (CWE-352) |
| [WebGoat-Legacy](https://github.com/OWASP/WebGoat-Legacy) | Java | Insecure deserialization, XXE, auth bypass |
| [NodeGoat](https://github.com/OWASP/NodeGoat) | JavaScript | NoSQL injection, session fixation, crypto issues |
| [Juice Shop](https://github.com/juice-shop/juice-shop) | JavaScript | IDOR, auth bypass, injection flaws |

## Expected SARIF Output Format

SOVA generates SARIF 2.1.0 compliant reports with:
- Vulnerability rule IDs (CWE classifications)
- Severity levels (Critical/High/Medium/Low)
- File locations and line numbers
- Code snippets showing vulnerable patterns
- Remediation recommendations

Example SARIF finding:
```json
{
  "ruleId": "CWE-89",
  "level": "error",
  "message": {"text": "SQL Injection vulnerability detected"},
  "locations": [{
    "physicalLocation": {
      "artifactLocation": {"uri": "src/database.py"},
      "region": {
        "startLine": 42,
        "snippet": {"text": "query = f\"SELECT * FROM users WHERE id={user_id}\""}
      }
    }
  }]
}
```

## Troubleshooting

**Scan fails with timeout**: Increase `OPENSHELL_EXEC_TIMEOUT` environment variable (default: 120s)

**Repository too large**: SOVA enforces a 500MB clone size limit for security

**Egress blocked during clone**: Ensure git repository URLs are allowlisted in OpenShell policy

**No vulnerabilities found**: Test repositories may require specific branches or configurations
```
