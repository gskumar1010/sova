#!/usr/bin/env bash
# verify-kata.sh -- Verify that Kata Containers is installed and functional
#
# Checks:
#   1. The 'kata' RuntimeClass exists
#   2. A test pod can run with the kata RuntimeClass
#
# Usage: ./1-infra/verify-kata.sh
# Requires: oc CLI logged in with cluster-admin privileges

set -euo pipefail

echo "=== Kata Containers Verification ==="
echo ""

# Check 1: RuntimeClass exists
echo -n "Checking for 'kata' RuntimeClass... "
if oc get runtimeclass kata >/dev/null 2>&1; then
    echo "FOUND"
else
    echo "NOT FOUND"
    echo ""
    echo "ERROR: The 'kata' RuntimeClass does not exist."
    echo "Ensure the OpenShift Sandboxed Containers operator is installed"
    echo "and the KataConfig CR has been applied."
    exit 1
fi

# Check 2: Test pod with Kata runtime
echo "Launching test pod with kata RuntimeClass..."
TEST_POD="kata-verify-$$"
oc run "${TEST_POD}" \
    --image=registry.access.redhat.com/ubi9/ubi-minimal:latest \
    --restart=Never \
    --overrides='{"spec":{"runtimeClassName":"kata"}}' \
    --command -- cat /proc/version

echo "Waiting for test pod to complete..."
if oc wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${TEST_POD}" \
    --timeout=120s 2>/dev/null; then
    echo ""
    echo "Guest kernel version:"
    oc logs "${TEST_POD}" 2>/dev/null | sed 's/^/  /'
    echo ""
    echo "RESULT: Kata is functional."
else
    echo ""
    echo "ERROR: Test pod did not succeed. Check pod status:"
    oc get pod "${TEST_POD}" -o wide 2>/dev/null || true
    oc delete pod "${TEST_POD}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    exit 1
fi

# Clean up test pod
oc delete pod "${TEST_POD}" --ignore-not-found --wait=false >/dev/null 2>&1 || true

echo ""
echo "=== Verification complete ==="
