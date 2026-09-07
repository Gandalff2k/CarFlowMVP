#!/usr/bin/env bash
.
set -euo pipefail

: "${NETWORK_NAME:?source deploy/hetzner/env.sh first}"
: "${SSH_KEY_NAME:?source deploy/hetzner/env.sh first}"

echo "==> network"
hcloud network create --name "$NETWORK_NAME" --ip-range 10.0.0.0/16
hcloud network add-subnet "$NETWORK_NAME" --type cloud --network-zone eu-central --ip-range 10.0.1.0/24

echo "==> firewall (SSH + your current IP only for admin ports; intra-network traffic is unrestricted)"
MY_IP="$(curl -fsS https://ifconfig.me)"
hcloud firewall create --name "$FIREWALL_NAME"
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 22 --source-ips "${MY_IP}/32"
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 6443 --source-ips "${MY_IP}/32"   # k3s API
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 3000 --source-ips "${MY_IP}/32"   # grafana (NodePort, see deploy/k8s/observability.yaml)
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 16686 --source-ips "${MY_IP}/32" # jaeger UI
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 30080 --source-ips "${MY_IP}/32" # kong NodePort
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 30300 --source-ips "${MY_IP}/32" # grafana NodePort (alt, see note in observability.yaml)
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 8089 --source-ips "${MY_IP}/32" # locust web UI

echo "==> servers"
hcloud server create --name infra        --type cx32  --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-server   --type cpx21 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-agent-1  --type cpx31 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-agent-2  --type cpx31 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name loadgen      --type cpx31 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"

echo "==> waiting for private-network attachment"
sleep 15

echo "==> server IPs (save these — every later script needs them)"
printf "%-14s %-16s %s\n" "NAME" "PRIVATE_IP" "PUBLIC_IP"
for name in infra k3s-server k3s-agent-1 k3s-agent-2 loadgen; do
  priv="$(hcloud server describe "$name" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["private_net"][0]["ip"])')"
  pub="$(hcloud server describe "$name" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_net"]["ipv4"]["ip"])')"
  printf "%-14s %-16s %s\n" "$name" "$priv" "$pub"
done

echo "==> done. Next: ./deploy/hetzner/bootstrap-infra.sh <infra-private-ip> <infra-public-ip>"
