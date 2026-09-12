#!/usr/bin/env bash
# Single entry point: builds the file-derived ConfigMaps (Kong config,
# otel-collector config, Grafana provisioning + dashboards — all straight
# from the real files under infra/, zero duplication), creates the secret
# holding JWT/Stripe material, then renders the kustomize base and
# substitutes ${INFRA_PRIVATE_IP}/${GHCR_USER}/${IMAGE_TAG} before applying.

set -euo pipefail

INFRA_PRIVATE_IP="${1:?usage: deploy.sh <infra-private-ip>}"
export INFRA_PRIVATE_IP
: "${GHCR_USER:?source deploy/hetzner/env.sh first}"
: "${GHCR_TOKEN:?source deploy/hetzner/env.sh first}"
: "${IMAGE_TAG:?source deploy/hetzner/env.sh first}"
: "${JWT_SECRET:?source deploy/hetzner/env.sh first}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> namespace"
kubectl apply -f "$K8S_DIR/namespace.yaml"

echo "==> file-derived ConfigMaps (single source of truth: infra/)"
kubectl create configmap kong-config -n carflow \
  --from-file=kong.yml="$REPO_ROOT/infra/kong.yml" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create configmap otel-collector-config -n carflow \
  --from-file=config.yml="$REPO_ROOT/infra/otel-collector-config.yml" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create configmap grafana-datasources -n carflow \
  --from-file="$REPO_ROOT/infra/grafana/provisioning/datasources/" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create configmap grafana-dashboard-providers -n carflow \
  --from-file="$REPO_ROOT/infra/grafana/provisioning/dashboards/" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create configmap grafana-dashboards -n carflow \
  --from-file="$REPO_ROOT/infra/grafana/dashboards/" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> secret (JWT + Stripe test keys — never written to a YAML file in the repo)"
kubectl create secret generic carflow-secrets -n carflow \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=STRIPE_API_KEY="${STRIPE_API_KEY:-}" \
  --from-literal=STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> registry pull secret (GHCR packages default to private — without this, every pod ImagePullBackOffs)"
kubectl create secret docker-registry ghcr-pull -n carflow \
  --docker-server=ghcr.io \
  --docker-username="$GHCR_USER" \
  --docker-password="$GHCR_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> rendering + applying the app/observability manifests"
kubectl kustomize "$K8S_DIR" | envsubst | kubectl apply -f -

echo "==> waiting for rollouts"
for dep in auth listing booking payment search telemetry admin notification kong otel-collector jaeger prometheus grafana; do
  kubectl rollout status deployment/"$dep" -n carflow --timeout=180s
done

NODE_IP="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || true)"
echo "==> done."
echo "    Kong:     http://<any-agent-public-ip>:30080"
echo "    Grafana:  http://<any-agent-public-ip>:30300  (admin/admin by default)"
echo "    Jaeger:   http://<any-agent-public-ip>:30686"
[[ -n "$NODE_IP" ]] && echo "    (one node's IP, if resolvable here: $NODE_IP)"
