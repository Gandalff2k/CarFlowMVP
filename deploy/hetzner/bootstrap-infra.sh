#!/usr/bin/env bash
# Ships the repo's docker-compose.yml + infra/ to the infra VM and brings up
# only the stateful datastores (postgres, kafka, debezium, redis, mongo,
# elasticsearch) — none of the 9 app services or Kong run here; those go to
# k8s. Also creates the real Kafka topics with 6 partitions each.
set -euo pipefail

INFRA_PRIVATE_IP="${1:?usage: bootstrap-infra.sh <infra-private-ip> <infra-public-ip>}"
INFRA_PUBLIC_IP="${2:?usage: bootstrap-infra.sh <infra-private-ip> <infra-public-ip>}"
SSH_USER="${SSH_USER:-root}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> copying docker-compose.yml + infra/ to $INFRA_PUBLIC_IP"
ssh -o StrictHostKeyChecking=accept-new "${SSH_USER}@${INFRA_PUBLIC_IP}" "mkdir -p ~/carflow"
scp -o StrictHostKeyChecking=accept-new "$REPO_ROOT/docker-compose.yml" "${SSH_USER}@${INFRA_PUBLIC_IP}:~/carflow/"
scp -r -o StrictHostKeyChecking=accept-new "$REPO_ROOT/infra" "${SSH_USER}@${INFRA_PUBLIC_IP}:~/carflow/"

echo "==> installing docker (if missing) and starting the datastore services"
ssh "${SSH_USER}@${INFRA_PUBLIC_IP}" bash -s -- "$INFRA_PRIVATE_IP" <<'REMOTE'
set -euo pipefail
INFRA_PRIVATE_IP="$1"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
cd ~/carflow
export KAFKA_EXTERNAL_ADVERTISED_HOST="$INFRA_PRIVATE_IP"
docker compose up -d postgres kafka debezium redis mongo elasticsearch

echo "waiting for kafka to become healthy..."
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' carflow-kafka-1 2>/dev/null || echo starting)"
  [[ "$status" == "healthy" ]] && break
  sleep 5
done

echo "creating topics with 6 partitions each..."
for topic in listing.vehicle.events payment.booking.events booking.payment.commands telemetry.raw; do
  docker compose exec -T kafka kafka-topics --create --if-not-exists \
    --bootstrap-server kafka:29092 --topic "$topic" --partitions 6 --replication-factor 1
done
docker compose exec -T kafka kafka-topics --describe --bootstrap-server kafka:29092

echo "waiting for debezium to become healthy..."
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' carflow-debezium-1 2>/dev/null || echo starting)"
  [[ "$status" == "healthy" ]] && break
  sleep 5
done

echo "registering debezium connectors..."
bash ~/carflow/infra/debezium/register-connectors.sh
REMOTE

echo "==> done. Datastores are up on $INFRA_PUBLIC_IP (private IP $INFRA_PRIVATE_IP)."
echo "    Next: ./deploy/hetzner/bootstrap-k3s.sh <k3s-server-public-ip> <agent-1-public-ip> <agent-2-public-ip>"
