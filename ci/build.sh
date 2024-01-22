#!/usr/bin/env bash
set -eu

SCRIPTDIR=${BASH_SOURCE%/*}
. "$SCRIPTDIR/setup.env"
cd "$SCRIPTDIR/.."

echo "::group::Build kaniko-runner image"
$ENGINE build -t "$KANIKORUNNER_IMAGE" ./kaniko-runner/
echo "::endgroup::"

echo "::group::Build repo2kaniko image"
$ENGINE build -t "$REPO2KANIKO_IMAGE" ./
echo "::endgroup::"
