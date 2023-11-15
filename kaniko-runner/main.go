package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/containers/common/pkg/auth"
	"github.com/containers/image/v5/types"
)

type inputRequest struct {
	Command     []string           `json:"command"`
	Credentials []inputCredentials `json:"credentials"`
}

type inputCredentials struct {
	Registry string `json:"registry"`
	Username string `json:"username"`
	Password string `json:"password"`
	Insecure bool   `json:"insecure"`
}

func listen(addr string) (net.Listener, error) {
	parts, err := url.Parse(addr)
	if err != nil {
		return nil, err
	}

	if parts.Scheme == "tcp" {
		log.Printf("Listening on tcp://%s", parts.Host)
		return net.Listen("tcp", parts.Host)
	} else if parts.Scheme == "unix" {
		log.Printf("Listening on unix://%s%s", parts.Host, parts.Path)
		return net.Listen("unix", parts.Host+parts.Path)
	} else {
		return nil, errors.New("unsupported network type")
	}
}

func returnError(conn net.Conn, err error) {
	fmt.Fprintln(conn, err)
	log.Println(err)
	fmt.Fprintln(conn, "status: FAILED")
}

func dockerConfigPath() string {
	executable, err := os.Executable()
	if err != nil {
		panic(err)
	}
	executableDir := filepath.Dir(executable)
	return filepath.Join(executableDir, ".docker", "config.json")
}

func handleConnection(conn net.Conn) {
	defer conn.Close()

	// Read the incoming command from the client
	inputJson, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		return
	}

	// input is a JSON object like:
	// {
	//   "command": ["string", "string", ...],
	//   "credentials": [{
	//     "registry": "https://index.docker.io/v1/",
	//		 "username": "username",
	//		 "password": "password",
	//		 "insecure": false
	//   },
	//   ...]
	// }
	var input inputRequest
	if err := json.Unmarshal([]byte(inputJson), &input); err != nil {
		returnError(conn, err)
		return
	}

	for _, cred := range input.Credentials {
		ctx := context.Background()
		// var cancel context.CancelFunc = func() {}
		// ctx, cancel = context.WithTimeout(ctx, 1000)
		// defer cancel()

		// Login to the registry
		systemCtx := types.SystemContext{}
		if cred.Insecure {
			systemCtx.DockerInsecureSkipTLSVerify = types.OptionalBoolTrue
		}
		opts := auth.LoginOptions{
			AuthFile: dockerConfigPath(),
			Username: cred.Username,
			Password: cred.Password,
			Verbose:  true,
			Stdout:   os.Stdout,
		}
		log.Printf("Logging in to %s", cred.Registry)
		args := []string{cred.Registry}
		if err := auth.Login(ctx, &systemCtx, &opts, args); err != nil {
			returnError(conn, err)
			return
		}
	}

	log.Printf("Running command: %s", input.Command)

	// Run the command
	cmd := exec.Command(input.Command[0], input.Command[1:]...)

	// Get the output of the command
	stdout, erro := cmd.StdoutPipe()
	if erro != nil {
		returnError(conn, erro)
		return
	}
	stderr, erre := cmd.StderrPipe()
	if erre != nil {
		returnError(conn, erre)
		return
	}

	// Create a multiwriter that writes to both the console and the connection
	stdoutWriter := io.MultiWriter(os.Stdout, conn)
	stderrWriter := io.MultiWriter(os.Stderr, conn)

	if err := cmd.Start(); err != nil {
		returnError(conn, err)
		return
	}

	// Use goroutines to handle stdout and stderr separately
	go io.Copy(stdoutWriter, stdout) //nolint:errcheck
	go io.Copy(stderrWriter, stderr) //nolint:errcheck

	if err = cmd.Wait(); err != nil {
		returnError(conn, err)
		return
	}
	fmt.Fprintln(conn, "status: SUCCESS")
}

func main() {
	var listenAddr string
	flag.StringVar(&listenAddr, "address", "tcp://localhost:8080", "address to listen on, e.g. unix:///tmp/go-runner.sock, tcp://localhost:8080")
	flag.Parse()

	ln, err := listen(listenAddr)
	if err != nil {
		panic(err)
	}

	for {
		conn, err := ln.Accept()
		if err != nil {
			panic(err)
		}

		go handleConnection(conn)
	}
}
