#!/usr/bin/env bash

set -euo pipefail

: "${GHCR_USER:?source deploy/hetzner/env.sh first}"
: "${GHCR_TOKEN:?source deploy/hetzner/env.sh first}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> logging in to ghcr.io as $GHCR_USER"
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin

services=(auth listing booking payment search telemetry admin notification)

for svc in "${services[@]}"; do
  image="ghcr.io/${GHCR_USER}/carflow-${svc}:${IMAGE_TAG}"
  echo "==> building $image"
  docker build -f "$REPO_ROOT/services/${svc}/Dockerfile" -t "$image" "$REPO_ROOT"
  echo "==> pushing $image"
  docker push "$image"
done

echo "==> done. IMAGE_TAG=$IMAGE_TAG — pass it to deploy/k8s/deploy.sh (env var IMAGE_TAG, same name)."
