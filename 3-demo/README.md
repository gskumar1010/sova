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
| Travel agent | Returns an itinerary via the allowlisted travel API | Itinerary with flight/hotel from travel API data |
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

--- Check 1: Travel Agent (happy path) ---
  [PASS] Agent returned a travel itinerary from the travel API

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
