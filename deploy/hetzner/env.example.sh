#!/usr/bin/env bash


export NETWORK_NAME=carflow-net
export FIREWALL_NAME=carflow-fw
export SSH_KEY_NAME=carflow          # must already exist: hcloud ssh-key create --name carflow --public-key-from-file ~/.ssh/id_ed25519.pub
export LOCATION=nbg1
export IMAGE=ubuntu-24.04

export GHCR_USER=your-github-username
export GHCR_TOKEN=ghp_xxx            # needs write:packages scope
export IMAGE_TAG=local               # push-images.sh overwrites this with the current git short SHA if unset

# Only needed if you actually want Stripe test-mode payments during the load
# test; the payment service runs fine without them (STRIPE_API_KEY empty is
# the same as local dev's default).
export STRIPE_API_KEY=
export STRIPE_WEBHOOK_SECRET=

# Must match auth's JWT_SECRET/JWT_ISSUER and infra/kong.yml's consumer
# secret — kept out of any committed YAML, injected as a k8s Secret instead.
export JWT_SECRET=dev-secret
export JWT_ISSUER=carflow-auth
