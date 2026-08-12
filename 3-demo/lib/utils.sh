#!/usr/bin/env bash
# Shared utility functions for verification

NAMESPACE="${NAMESPACE:-openshell-kata}"
SANDBOX_NAME="opencode-dual"

# Execute a command in the sandbox via openshell sandbox exec.
# This ensures the command runs inside the supervised sandbox
# (network namespace with policy proxy active).
pod_exec() {
    openshell sandbox exec -n "${SANDBOX_NAME}" --no-tty --timeout 300 -- "$@" 2>&1
}

# Resolve the actual Kubernetes pod name for the sandbox. OpenShell prefixes
# the sandbox pod name (e.g. "default--opencode-dual"), so match the pod whose
# name is exactly the sandbox name or ends with "--<sandbox name>".
sandbox_pod_name() {
    oc get pods -n "${NAMESPACE}" -o name 2>/dev/null \
        | sed 's|^pod/||' \
        | grep -E -- "(^|--)${SANDBOX_NAME}$" \
        | head -1
}

# Check if the sandbox pod is running
pod_ready() {
    local pod status
    pod=$(sandbox_pod_name)
    [ -n "${pod}" ] || return 1
    status=$(oc get pod "${pod}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.phase}' 2>/dev/null)
    [ "${status}" = "Running" ]
}
