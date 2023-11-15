default: build

lint:
	golangci-lint run

build:
	go build $(GOFLAGS) -o kaniko-runner .

clean:
	rm -f kaniko-runner

container:
	podman build -t kaniko-runner .

update-deps:
	go get -t -u ./...
	go mod tidy
