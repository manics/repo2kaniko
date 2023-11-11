# repo2kaniko

[![Build Status](https://github.com/manics/repo2kaniko/actions/workflows/build.yml/badge.svg)](https://github.com/manics/repo2kaniko/actions/workflows/build.yml)
[![Container repository](https://img.shields.io/badge/quay.io-container-purple)](https://quay.io/repository/manics/repo2kaniko?tab=tags)

`repo2kaniko` is a plugin for [repo2docker](http://repo2docker.readthedocs.io) that lets you use [Kaniko](https://github.com/GoogleContainerTools/kaniko) instead of Docker.

Kaniko must run in a container, can only build images, and can only store images in a registry.
It has the big advantage that it i completely unprivileged and doesn't require any host configuration, unlike e.g. Podman which requires your system to have the correct cgroups configuration.

It does not use a local Docker store, so it is not possible to separate the build and push steps.
**This means the repo2docker `--push`/`--no-push` arguments have no effect.**
The default in this plugin is to automatically push the image to a registry after it is built.
Set Traitlet `KanikoEngine.push_image=False` or environment variable `KANIKO_PUSH_IMAGE=0` to disable pushing the image.

Kaniko does not cache layers locally, instead it uses a registry for caching.
You should probably use a dedicated local private registry for speed and not the remote registry used for storing the built image.
Use `KanikoEngine.cache_registry_credentials` or `KANIKO_CACHE_REGISTRY_CREDENTIALS` to specify the credentials for the cache registry.
These behave similarly to `ContainerEngine.registry_credentials` and `CONTAINER_ENGINE_REGISTRY_CREDENTIALS`.

## Running

```
podman run -it --rm quay.io/manics/repo2kaniko \
    repo2docker --debug --engine=kaniko \
    --Repo2Docker.user_id=1000 --user-name=jovyan \
    --KanikoEngine.registry_credentials=registry=quay.io \
    --KanikoEngine.registry_credentials=username=quay-user \
    --KanikoEngine.registry_credentials=password=quay-password \
    --image-name=quay.io/quay-user/r2d-test \
    --no-run \
    https://github.com/binderhub-ci-repos/minimal-dockerfile
```

With a local registry that can be used as a cache:

```
./run-local-registry.sh
REGISTRY=...
podman run -it --rm quay.io/manics/repo2kaniko \
    repo2docker --debug --engine=kaniko \
    --Repo2Docker.user_id=1000 --user-name=jovyan \
    --KanikoEngine.cache_registry=$REGISTRY/cache \
    --KanikoEngine.cache_registry_credentials=username=user \
    --KanikoEngine.cache_registry_credentials=password=password \
    --KanikoEngine.cache_registry_insecure=true \
    --image-name=$REGISTRY/r2d-test \
    --no-run \
    https://github.com/binderhub-ci-repos/minimal-dockerfile
```
