#!/usr/bin/env bash

set -euo pipefail

: "${NETWORK_NAME:?source deploy/hetzner/env.sh first}"
: "${FIREWALL_NAME:?source deploy/hetzner/env.sh first}"

echo "About to delete: servers (infra, k3s-server, k3s-agent-1, k3s-agent-2, loadgen),"
echo "firewall ($FIREWALL_NAME), network ($NETWORK_NAME), and any volumes attached to them."
read -r -p "Type 'yes' to proceed: " confirm
[[ "$confirm" == "yes" ]] || { echo "aborted"; exit 1; }

for name in infra k3s-server k3s-agent-1 k3s-agent-2 loadgen; do
  hcloud server delete "$name" 2>/dev/null || echo "  (already gone: $name)"
done

echo "==> checking for leftover volumes and floating IPs (these bill even when detached)"
hcloud volume list
hcloud floating-ip list

hcloud firewall delete "$FIREWALL_NAME" 2>/dev/null || true
hcloud network delete "$NETWORK_NAME" 2>/dev/null || true

echo "==> done. If the volume/floating-ip lists above weren't empty, delete those manually:"
echo "    hcloud volume delete <name>   /   hcloud floating-ip delete <name>"
