#!/usr/bin/env bash
# Installs k3s via k3sup: one server, two agents. Traefik and servicelb are
# disabled — Kong replaces Traefik as the ingress path, and servicelb is skipped entirely since Kong is
# exposed via a fixed NodePort instead .
set -euo pipefail

K3S_SERVER_IP="${1:?usage: bootstrap-k3s.sh <k3s-server-public-ip> <agent-1-public-ip> <agent-2-public-ip>}"
AGENT1_IP="${2:?usage: bootstrap-k3s.sh <k3s-server-public-ip> <agent-1-public-ip> <agent-2-public-ip>}"
AGENT2_IP="${3:?usage: bootstrap-k3s.sh <k3s-server-public-ip> <agent-1-public-ip> <agent-2-public-ip>}"
SSH_USER="${SSH_USER:-root}"

if ! command -v k3sup >/dev/null 2>&1; then
  echo "k3sup not found locally — installing to /usr/local/bin (needs sudo)"
  curl -sLS https://get.k3sup.dev | sh
  sudo install k3sup /usr/local/bin/
fi

echo "==> installing k3s server"
k3sup install \
  --ip "$K3S_SERVER_IP" \
  --user "$SSH_USER" \
  --k3s-extra-args '--disable traefik --disable servicelb --write-kubeconfig-mode 644' \
  --local-path ./kubeconfig \
  --context carflow

export KUBECONFIG=./kubeconfig

echo "==> joining agent-1"
k3sup join --ip "$AGENT1_IP" --server-ip "$K3S_SERVER_IP" --user "$SSH_USER"

echo "==> joining agent-2"
k3sup join --ip "$AGENT2_IP" --server-ip "$K3S_SERVER_IP" --user "$SSH_USER"

echo "==> waiting for nodes"
kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl get nodes -o wide

echo "==> installing metrics-server (required by HPA)"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# k3s nodes commonly need --kubelet-insecure-tls since there's no real
# cluster CA chain for the kubelet cert here (single-node-per-role, private
# network only — acceptable for a short-lived load-test cluster).
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl rollout status deployment metrics-server -n kube-system --timeout=120s

echo "==> done. kubeconfig written to ./kubeconfig — export KUBECONFIG=\$(pwd)/kubeconfig"
echo "    Next: ./deploy/hetzner/push-images.sh, then ./deploy/k8s/deploy.sh <infra-private-ip>"
