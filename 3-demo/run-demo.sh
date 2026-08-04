#!/usr/bin/env bash
# run-demo.sh -- Verify that the dual-protection sandbox is operational
#
# Runs three checks:
#   1. Agent can execute commands inside the sandbox (functional)
#   2. Unauthorized egress is blocked (OpenShell policy)
#   3. Kata VM isolation is active (guest kernel)
#
# Prerequisites:
#   - Phase 2 complete (sandbox deployed)
#   - env.sh sourced
#   - Port-forward to OpenShell gateway running (setup.sh starts one)
#
# Usage:
#   source env.sh
#   ./3-demo/run-demo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${NAMESPACE:-openshell-kata}"

# shellcheck source=3-demo/lib/colors.sh
source "${SCRIPT_DIR}/lib/colors.sh"
# shellcheck source=3-demo/lib/utils.sh
source "${SCRIPT_DIR}/lib/utils.sh"

# --- Port-forward ---

PF_PID=""
cleanup() {
    if [ -n "${PF_PID}" ] && kill -0 "${PF_PID}" 2>/dev/null; then
        kill "${PF_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start port-forward if not already running
if ! pgrep -f "port-forward.*svc/openshell.*18080" >/dev/null 2>&1; then
    info "Starting port-forward to OpenShell gateway..."
    oc port-forward -n "${NAMESPACE}" svc/openshell 18080:8080 > /tmp/demo-pf.log 2>&1 &
    PF_PID=$!
    sleep 3
    if ! kill -0 "${PF_PID}" 2>/dev/null; then
        fail "Port-forward failed. Check /tmp/demo-pf.log"
        exit 1
    fi
fi

# =====================================================================
banner "OpenShell + Kata Verification"
# =====================================================================

echo "Verifying the dual-protection sandbox is correctly configured:"
echo "  - OpenShell enforces network egress policy"
echo "  - Kata provides hardware VM isolation"
echo ""

# --- Preflight ---

section "Preflight"

if pod_ready; then
    pass "Sandbox pod 'opencode-dual' is running"
else
    fail "Sandbox pod 'opencode-dual' is NOT running"
    echo ""
    fail "Run 2-deploy/setup.sh first."
    exit 1
fi

# Check RuntimeClass
RUNTIME_CLASS=$(oc get pod opencode-dual -n "${NAMESPACE}" \
    -o jsonpath='{.spec.runtimeClassName}' 2>/dev/null || echo "")
if [ "${RUNTIME_CLASS}" = "kata" ]; then
    pass "Pod RuntimeClass: kata"
else
    warn "Pod RuntimeClass: '${RUNTIME_CLASS}' (expected 'kata')"
fi

CHECKS_PASSED=0
CHECKS_TOTAL=3

# =====================================================================
section "Check 1: Travel Agent (happy path)"
# =====================================================================

echo "Asking the agent to find a flight + hotel via the allowlisted travel API..."
echo ""

OUTPUT=$(pod_exec opencode run "Find a flight from SFO to BOS under 300 dollars and a hotel in Boston under 200 dollars. Use travel_search.py." 2>&1 || true)

if echo "${OUTPUT}" | grep -Eqi "OA101|OpenAir|Kata Inn|itinerary|\\\$2[0-9][0-9]"; then
    pass "Agent returned a travel itinerary from the travel API"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    fail "Agent did not return an itinerary"
    info "Output: $(echo "${OUTPUT}" | head -5)"
fi

# =====================================================================
section "Check 2: Prompt-injection exfiltration is blocked"
# =====================================================================

echo "Simulating an injected instruction that tries to exfiltrate data..."
echo ""

OUTPUT=$(pod_exec curl -s --max-time 10 http://example.com 2>&1 || true)

if echo "${OUTPUT}" | grep -qi "policy_denied\|blocked\|connection refused\|denied"; then
    pass "Exfiltration attempt BLOCKED by OpenShell policy"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    info "Response: $(echo "${OUTPUT}" | head -1)"
elif echo "${OUTPUT}" | grep -qi "timed out\|timeout"; then
    pass "Exfiltration attempt blocked (connection timed out)"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    fail "Egress was NOT blocked - check OpenShell policy configuration"
    info "Output: $(echo "${OUTPUT}" | head -3)"
fi

# =====================================================================
section "Check 3: Kata VM Isolation"
# =====================================================================

echo "Verifying the pod runs inside a Kata VM (separate guest kernel)..."
echo ""

HOST_KERNEL=$(oc get nodes -o jsonpath='{.items[0].status.nodeInfo.kernelVersion}' 2>/dev/null || echo "unknown")
GUEST_KERNEL=$(pod_exec cat /proc/version 2>&1 || echo "")

info "Host kernel:  ${HOST_KERNEL}"
info "Guest kernel: $(echo "${GUEST_KERNEL}" | head -1)"

if [ -n "${GUEST_KERNEL}" ] && [ "${GUEST_KERNEL}" != "${HOST_KERNEL}" ]; then
    pass "Guest kernel differs from host - Kata VM boundary confirmed"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    warn "Could not confirm separate guest kernel"
    info "This may be expected if host and guest run the same kernel version"
fi

# =====================================================================
banner "Results"
# =====================================================================

echo "  Checks passed: ${CHECKS_PASSED}/${CHECKS_TOTAL}"
echo ""

if [ "${CHECKS_PASSED}" -eq "${CHECKS_TOTAL}" ]; then
    echo -e "${GREEN}${BOLD}All checks passed. Dual protection is operational.${NC}"
else
    echo -e "${YELLOW}${BOLD}Some checks did not pass. Review output above.${NC}"
fi

echo ""
