# https://www.docker.com/blog/faster-multi-platform-builds-dockerfile-cross-compilation-guide/

###########################################################################
FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.21-alpine AS build

RUN apk add --no-cache make git

WORKDIR /src
COPY go.mod go.sum main.go Makefile ./

ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH make build

###########################################################################
FROM gcr.io/kaniko-project/executor:v1.18.0-debug as kaniko

COPY --from=build /src/kaniko-runner /kaniko/

EXPOSE 8080
ENTRYPOINT ["/kaniko/kaniko-runner"]
