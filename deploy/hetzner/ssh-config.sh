#!/usr/bin/env bash
# Prints an ~/.ssh/config snippet for all 5 servers, so `ssh carflow-infra`
# etc. works instead of copy-pasting IPs. This is the only SSH you'll do by
# hand: k3sup does its own SSH for the k3s install/join, and app-service
# access goes through kubectl (API server), not SSH, once the cluster is up.
#
# Usage:
#   ./deploy/hetzner/ssh-config.sh >> ~/.ssh/config
set -euo pipefail

for name in infra k3s-server k3s-agent-1 k3s-agent-2 loadgen; do
  ip="$(hcloud server ip "$name")"
  cat <<EOF
Host carflow-${name}
    HostName ${ip}
    User root
    StrictHostKeyChecking accept-new

EOF
done
