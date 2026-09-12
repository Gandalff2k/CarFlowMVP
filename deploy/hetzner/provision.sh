#!/usr/bin/env bash
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
# NodePort services are reached on the node's actual NodePort number, not
# the pod's internal port — 3000/16686 (Grafana/Jaeger's container ports)
# are not reachable from outside the cluster at all, only 30300/30686 are.
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 30080 --source-ips "${MY_IP}/32" # kong NodePort
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 30300 --source-ips "${MY_IP}/32" # grafana NodePort
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 30686 --source-ips "${MY_IP}/32" # jaeger UI NodePort
hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 8089 --source-ips "${MY_IP}/32" # locust web UI

echo "==> servers"
# Bumped to Hetzner's dedicated-vCPU line (ccx) for a bigger, cleaner test:
# a shared-vCPU node (cx/cpx) can get CPU-steal jitter from other tenants,
# which would contaminate exactly the measurement this test exists to take
# (does the Kafka-partition fix + HPA actually scale). ccx43 (16 vCPU/64GB)
# for infra keeps Postgres/Kafka/ES comfortably out of memory pressure —
# see deploy/RUNBOOK.md for the max_connections math and why 64GB, not
# 128GB. k3s-server stays cpx21: nothing gets scheduled there regardless of
# how big the test gets.
hcloud server create --name infra        --type ccx43 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-server   --type cpx21 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-agent-1  --type ccx33 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name k3s-agent-2  --type ccx33 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"
hcloud server create --name loadgen      --type ccx33 --image "$IMAGE" --location "$LOCATION" --network "$NETWORK_NAME" --firewall "$FIREWALL_NAME" --ssh-key "$SSH_KEY_NAME"

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
