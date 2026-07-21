#!/usr/bin/env bash
# teardown.sh -- Remove all quickstart resources from the cluster
#
# Usage:
#   source env.sh
#   ./2-deploy/teardown.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${NAMESPACE:-openshell-kata}"

info() { echo "==> $*"; }

info "Tearing down OpenShell + Kata deployment..."

# Delete OpenShell sandbox
info "Deleting OpenShell sandbox..."
openshell sandbox delete opencode-dual 2>/dev/null || true

# Delete secrets and ConfigMaps
info "Deleting secrets and ConfigMaps..."
oc delete configmap opencode-config -n "${NAMESPACE}" --ignore-not-found
oc delete secret opencode-api-keys -n "${NAMESPACE}" --ignore-not-found
oc delete secret openshell-jwt-keys -n "${NAMESPACE}" --ignore-not-found

# Uninstall OpenShell
info "Uninstalling OpenShell gateway..."
helm uninstall openshell -n "${NAMESPACE}" 2>/dev/null || true

# Remove Kustomize-managed resources
info "Removing namespace and SCC..."
oc delete -k "${SCRIPT_DIR}" --ignore-not-found 2>/dev/null || true

echo ""
info "Teardown complete."
info "Note: The Kata operator and KataConfig are NOT removed."
info "Remove them manually if needed:"
info "  oc delete kataconfig default"
info "  oc delete subscription sandboxed-containers-operator -n openshift-sandboxed-containers-operator"
