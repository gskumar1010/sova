#!/usr/bin/env bash
# Shared utility functions for verification

NAMESPACE="${NAMESPACE:-openshell-kata}"
SANDBOX_NAME="opencode-dual"

# Execute a command in the sandbox via openshell sandbox exec.
# This ensures the command runs inside the supervised sandbox
# (network namespace with policy proxy active).
pod_exec() {
    openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty --timeout 120 -- "$@" 2>&1
}

# Check if the sandbox pod is running
pod_ready() {
    local status
    status=$(oc get pod "${SANDBOX_NAME}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.phase}' 2>/dev/null)
    [ "${status}" = "Running" ]
}
