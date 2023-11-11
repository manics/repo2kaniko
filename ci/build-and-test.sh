#!/usr/bin/env bash
set -eu

SCRIPTDIR=${BASH_SOURCE%/*}
cd "$SCRIPTDIR/.."

REPO2KANIKO_IMAGE=repo2kaniko:ci

REGISTRY=${REGISTRY_HOST:-}
if [ -z "$REGISTRY" ]; then
  # Use public IP when inside a container
  REGISTRY=$(hostname -I | awk '{print $1}'):5000
fi

PUSHED_IMAGE=$REGISTRY/test-conda:ci

if command -v podman; then
  ENGINE=podman
elif command -v docker; then
  ENGINE=docker
else
  echo "Neither podman nor docker are installed"
  exit 1
fi

echo "::group::Build repo2kaniko image"
$ENGINE build -t "$REPO2KANIKO_IMAGE" ./
echo "::endgroup::"

echo "::group::Run repo2kaniko"
$ENGINE run --rm --network=host -v "$PWD/ci/test-conda:/test-conda:ro,z" \
  "$REPO2KANIKO_IMAGE" repo2docker --engine kaniko --no-run --debug \
  --user-id=1000 --user-name=jovyan --image-name $PUSHED_IMAGE \
  --KanikoEngine.registry_credentials=registry=$REGISTRY \
  --KanikoEngine.registry_credentials=username=user \
  --KanikoEngine.registry_credentials=password=password \
  --KanikoEngine.registry_credentials=tls-verify=false \
  --KanikoEngine.cache_registry=$REGISTRY/cache \
  /test-conda
echo "::endgroup::"

echo "::group::Check repo2kaniko"
echo password | $ENGINE login --username=user --password-stdin --tls-verify=false localhost:5000
$ENGINE pull localhost:5000/test-conda:ci
echo "repo2docker --version:"
$ENGINE run $REPO2KANIKO_IMAGE repo2docker --version
echo "/home/jovyan/verify:"
$ENGINE run --rm localhost:5000/test-conda:ci /home/jovyan/verify

./ci/check-registry.py
echo "::endgroup::"
