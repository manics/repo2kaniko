#!/bin/sh
# https://distribution.github.io/distribution/about/deploying/#native-basic-auth

set -eu

# Create htpasswd file with brcrypt for basic auth
# Username: user
# Password: password
htpasswd -Bbn user password > registry.htpasswd

podman run -it --rm --name registry \
  -p 5000:5000 \
  -v $(pwd)/registry.htpasswd:/etc/docker/registry/htpasswd:ro,z \
  -e REGISTRY_AUTH=htpasswd \
  -e REGISTRY_AUTH_HTPASSWD_REALM=Registry \
  -e REGISTRY_AUTH_HTPASSWD_PATH=/etc/docker/registry/htpasswd \
  docker.io/library/registry:2.8.3
