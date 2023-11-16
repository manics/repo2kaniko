package main

import (
	"bufio"
	"encoding/base64"
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
	"strings"
	"time"
)

type inputRequest struct {
	Command     []string           `json:"command"`
	Credentials []inputCredentials `json:"credentials"`
}

type inputCredentials struct {
	Registry string `json:"registry"`
	// Either set Auth (base64 string), or Username + Password
	Auth     string `json:"auth"`
	Username string `json:"username"`
	Password string `json:"password"`
	Insecure bool   `json:"insecure"`
}

//	{
//	  "auths": {
//	     "host": {
//	       "auth": "base64"
//	     }
//		 }
//	}
type dockerConfigAuths struct {
	Auths map[string]dockerConfigAuth `json:"auths"`
}

type dockerConfigAuth struct {
	Auth string `json:"auth"`
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

func loadDockerConfig() (dockerConfigAuths, error) {
	var config dockerConfigAuths
	configPath := dockerConfigPath()
	if _, err := os.Stat(configPath); err == nil {
		configFile, err := os.Open(configPath)
		if err != nil {
			return config, err
		}
		defer configFile.Close()

		if err := json.NewDecoder(configFile).Decode(&config); err != nil {
			return config, err
		}
	}
	if config.Auths == nil {
		config.Auths = make(map[string]dockerConfigAuth)
	}
	return config, nil
}

func saveDockerConfig(config dockerConfigAuths) error {
	configPath := dockerConfigPath()
	configDir := filepath.Dir(configPath)
	if err := os.MkdirAll(configDir, 0700); err != nil {
		return err
	}

	configFile, err := os.Create(configPath)
	if err != nil {
		return err
	}
	defer configFile.Close()

	encoder := json.NewEncoder(configFile)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(config); err != nil {
		return err
	}

	return nil
}

func handleConnection(conn net.Conn) error {
	defer conn.Close()

	// Read the incoming command from the client
	inputJson, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		return err
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
		return err
	}

	dockerConfig, err := loadDockerConfig()

	if len(input.Credentials) > 0 {
		// Load the existing docker config
		if err != nil {
			returnError(conn, err)
			return err
		}

		for _, cred := range input.Credentials {
			// Add the credentials to the docker config
			if cred.Auth != "" && cred.Username != "" {
				err := errors.New("cannot specify both auth and username/password")
				returnError(conn, err)
				return err
			}
			if cred.Auth != "" {
				dockerConfig.Auths[cred.Registry] = dockerConfigAuth{Auth: cred.Auth}
			} else {
				auth := base64.StdEncoding.EncodeToString([]byte(cred.Username + ":" + cred.Password))
				dockerConfig.Auths[cred.Registry] = dockerConfigAuth{Auth: auth}
			}
		}
	}

	// log the registries from dockerConfig
	var registries []string
	for registry := range dockerConfig.Auths {
		registries = append(registries, registry)
	}
	log.Printf("Registries: %s", strings.Join(registries, " "))

	if err := saveDockerConfig(dockerConfig); err != nil {
		returnError(conn, err)
		return err
	}

	log.Printf("Running command: %s", input.Command)

	// Run the command
	cmd := exec.Command(input.Command[0], input.Command[1:]...)

	// Get the output of the command
	stdout, erro := cmd.StdoutPipe()
	if erro != nil {
		returnError(conn, erro)
		return erro
	}
	stderr, erre := cmd.StderrPipe()
	if erre != nil {
		returnError(conn, erre)
		return erre
	}

	// Create a multiwriter that writes to both the console and the connection
	stdoutWriter := io.MultiWriter(os.Stdout, conn)
	stderrWriter := io.MultiWriter(os.Stderr, conn)

	if err := cmd.Start(); err != nil {
		returnError(conn, err)
		return err
	}

	// Use goroutines to handle stdout and stderr separately
	go io.Copy(stdoutWriter, stdout) //nolint:errcheck
	go io.Copy(stderrWriter, stderr) //nolint:errcheck

	if err = cmd.Wait(); err != nil {
		returnError(conn, err)
		return err
	}
	fmt.Fprintln(conn, "status: SUCCESS")
	return nil
}

func main() {
	var listenAddr string
	flag.StringVar(&listenAddr, "address", "tcp://localhost:8080", "address to listen on, e.g. unix:///tmp/go-runner.sock, tcp://localhost:8080")
	var multiple bool
	flag.BoolVar(&multiple, "multiple", false, "Keep listening after request finishes, , not supported by Kaniko")
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

		if multiple {
			go handleConnection(conn) //nolint:errcheck
		} else {
			err := handleConnection(conn)
			// Give the client some time to read the output before exiting
			time.Sleep(2 * time.Second)
			if err != nil {
				log.Fatalf("ERROR: %v", err)
			}
			break
		}
	}
}
