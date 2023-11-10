FROM gcr.io/kaniko-project/executor:v1.18.0 as kaniko

FROM quay.io/jupyterhub/repo2docker:2023.06.0-41.g57d229e

# Install skopeo just so we can login to insecure registries
RUN apk add --no-cache skopeo

COPY --from=kaniko /kaniko /kaniko

COPY . /repo2kaniko
RUN pip install /repo2kaniko

# podman pod create --name=r2k --publish=8888:8888
# podman run --pod=r2k --rm -it registry
# podman run --pod=r2k --rm -it -v $PWD:/src:ro,z repo2kaniko bash
#
# https://docs.gitlab.com/ee/ci/docker/using_kaniko.html
#
# /kaniko/executor --cache=true --cache-dir=/cache --cache-repo=localhost:5000/cache --cache-copy-layers=true --cache-run-layers=true --context /src --dockerfile /src/Dockerfile --destination localhost:5000/a/b

# --cache-ttl <hours>
