#!/usr/bin/env bash
set -eu

SCRIPTDIR=${BASH_SOURCE%/*}
. "$SCRIPTDIR/setup.env"
cd "$SCRIPTDIR/.."

KANIKO_RUNNER_PORT=12321

echo "::group::Run kaniko-runner image"
mkdir -p ./ci/workspace
$ENGINE run -d --name kaniko-runner --rm -p12321:12321 \
  -v "$PWD/ci/workspace:/workspace:z" \
  "$KANIKORUNNER_IMAGE" -address=tcp://0.0.0.0:$KANIKO_RUNNER_PORT
sleep 1
$ENGINE logs kaniko-runner

clean_up () {
    $ENGINE rm -f kaniko-runner || :
} 
trap clean_up EXIT
echo "::endgroup::"

echo "::group::Run repo2kaniko"
REPO2DOCKER_ARGS="--engine kaniko --no-run --debug
  --user-id=1000 --user-name=jovyan --image-name $PUSHED_IMAGE
  --KanikoEngine.registry_credentials=registry=$REGISTRY_HOST
  --KanikoEngine.registry_credentials=username=user
  --KanikoEngine.registry_credentials=password=password
  --KanikoEngine.registry_credentials=tls-verify=false
  --KanikoEngine.cache_registry=$REGISTRY_HOST/cache
  --KanikoEngine.kaniko_address=tcp://$HOST_IP:$KANIKO_RUNNER_PORT"

if [ "${1-}" = repo2docker ]; then
  repo2docker $REPO2DOCKER_ARGS \
    --KanikoEngine.kaniko_build_path=$PWD/ci/workspace \
    ./ci/test-conda
elif [ "${1-}" = container ]; then
  # $ENGINE run --rm --network=host -v "$PWD/ci/test-conda:/test-conda:ro,z" \
  $ENGINE run --rm \
    -v "$PWD/ci/workspace:/workspace:z" \
    -v "$PWD/ci/test-conda:/test-conda:ro,z" \
    "$REPO2KANIKO_IMAGE" repo2docker $REPO2DOCKER_ARGS \
    ./test-conda
else
  echo "ERROR: Either 'container' or 'repo2docker' expected"
  exit 1
fi
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
