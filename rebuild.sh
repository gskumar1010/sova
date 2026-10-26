#!/usr/bin/env bash
# One-shot rebuild and redeploy for SOVA
set -euo pipefail

REGISTRY=default-route-openshift-image-registry.apps.cluster-lcqkj.dyn.redhatworkshops.io
NAMESPACE=openshell-kata
KUBECONFIG=/home/phknezev/.kube/sova-config

echo "==> Logging into OCP registry..."
podman login \
  --username="$(KUBECONFIG=$KUBECONFIG oc whoami)" \
  --password="$(KUBECONFIG=$KUBECONFIG oc whoami -t)" \
  "$REGISTRY"

echo "==> Building and pushing images..."
REGISTRY=$REGISTRY NAMESPACE=$NAMESPACE bash 2-deploy/build-images.sh --apps-only

echo "==> Restarting pod..."
KUBECONFIG=$KUBECONFIG oc rollout restart deployment/vuln-orchestrator-api -n "$NAMESPACE"
KUBECONFIG=$KUBECONFIG oc rollout status deployment/vuln-orchestrator-api -n "$NAMESPACE" --timeout=120s

echo ""
echo "==> Done. App is live at:"
echo "    https://sova-vue-openshell-kata.apps.cluster-lcqkj.dyn.redhatworkshops.io"
