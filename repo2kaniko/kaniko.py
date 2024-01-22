# Use Kaniko instead of Docker
import json
import os
import stat
import shutil
import socket
import tarfile
from tempfile import mkdtemp
from traitlets import default, Bool, Dict, TraitError, Unicode, validate
from urllib.parse import urlparse

from repo2docker.engine import (
    ContainerEngine,
)

from repo2podman.podman import (
    log_debug,
    log_info,
    execute_cmd,
    exec_podman,
    exec_podman_stream,
)


def _copy_or_chmod_tree(src, dst=None):
    """
    Similar to shutil.copytree, but
      - does not copy stat info (can cause problems when copying metadata such as selinux attributes)
      - ensures everything is world readable
      - if there is no dst then just chmods src
    """
    for item in os.listdir(src):
        src_path = os.path.join(src, item)
        if dst:
            dst_path = os.path.join(dst, item)
        else:
            dst_path = None
        src_permissions = stat.S_IMODE(os.lstat(src_path).st_mode)

        if os.path.isdir(src_path):
            if dst_path:
                os.makedirs(dst_path)
            os.chmod(
                dst_path or src_path,
                src_permissions
                | stat.S_IRUSR
                | stat.S_IRGRP
                | stat.S_IROTH
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH,
            )
            _copy_or_chmod_tree(src_path, dst_path)
        else:
            if dst_path:
                shutil.copyfile(src_path, dst_path, follow_symlinks=False)
            os.chmod(
                dst_path or src_path,
                src_permissions | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH,
            )


class KanikoEngine(ContainerEngine):
    """
    Kaniko build engine
    """

    kaniko_executable = Unicode(
        "/kaniko/executor",
        help="The kaniko executable to use for all commands.",
        config=True,
    )

    kaniko_address = Unicode(
        "tcp://localhost:8080",
        help=(
            "The address to connect to the Kaniko server. "
            "Set to empty to use the local Kaniko executor (not officially supported)."
        ),
        config=True,
    )

    kaniko_build_path = Unicode(
        "/workspace/",
        help=(
            "Absolute path to a shared directory for build context "
            "when a separate Kaniko container is used. "
            "Must be mounted to /workspace inside the Kaniko container."
        ),
        config=True,
    )

    @validate("kaniko_build_path")
    def _validate_kaniko_build_path(self, proposal):
        value = proposal["value"]
        # repo2docker may chdir into the cloned repo directory before calling
        # the engine, so we need to make sure the path is absolute
        if not os.path.isabs(value):
            raise TraitError("kaniko_build_path must be an absolute path")
        if not value.endswith(os.path.sep):
            value += os.path.sep
        return value

    login_executable = Unicode(
        "skopeo",
        help="The executable to use for registry login.",
        config=True,
    )

    kaniko_loglevel = Unicode("", help="Kaniko log level", config=True)

    push_image = Bool(
        help="Push built image, default true.",
        config=True,
    )

    @default("push_image")
    def _push_image_default(self):
        """
        Set push_image from KANIKO_PUSH_IMAGE
        """
        return os.getenv("KANIKO_PUSH_IMAGE", "1").lower() in ("1", "t", "true")

    cache_registry = Unicode(
        "",
        help="Use this image registry as a cache for the build, e.g. 'localhost:5000/cache'.",
        config=True,
    )

    cache_registry_insecure = Bool(
        False,
        help="Allow insecure connections to the cache registry.",
        config=True,
    )

    cache_registry_credentials = Dict(
        help="""
        Credentials dictionary, if set will be used to authenticate with
        the cache registry. Typically this will include the keys:

            - `username`: The registry username
            - `password`: The registry password or token

        This can also be set by passing a JSON object in the
        KANIKO_CACHE_REGISTRY_CREDENTIALS environment variable.
        """,
        config=True,
    )

    @default("cache_registry_credentials")
    def _cache_registry_credentials_default(self):
        """
        Set the registry credentials from KANIKO_CACHE_REGISTRY_CREDENTIALS
        """
        obj = os.getenv("KANIKO_CACHE_REGISTRY_CREDENTIALS")
        if obj:
            try:
                return json.loads(obj)
            except json.JSONDecodeError:
                self.log.error("KANIKO_CACHE_REGISTRY_CREDENTIALS is not valid JSON")
                raise
        return {}

    cache_dir = Unicode(
        "",
        help=(
            "Read-only directory pre-populated with base images. "
            "It is not used for caching layers. See "
            "https://github.com/GoogleContainerTools/kaniko/tree/v1.17.0#caching-base-images"
        ),
        config=True,
    )

    def __init__(self, *, parent):
        super().__init__(parent=parent)

        if self.kaniko_address:
            self._s = self._connect()
        else:
            self._s = None
            lines = exec_podman(
                ["version"], capture="stdout", exe=self.kaniko_executable
            )
            log_debug(lines)

    def _connect(self):
        url = urlparse(self.kaniko_address)
        if url.scheme == "tcp":
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((url.hostname, url.port))
        elif url.scheme == "unix":
            s = socket.socket(socket.AF_UNIX)
            s.connect(url.path)
        else:
            raise ValueError(f"Unsupported kaniko_address scheme {url.scheme}")
        return s

    def _create_build_context(self, fileobj, srcpath, builddir):
        if fileobj:
            tarf = tarfile.open(fileobj=fileobj)
            tarf.extractall(builddir)
            log_debug(builddir)

            lines = execute_cmd(["ls", "-lRa", builddir], capture="stdout")
            log_debug(lines)
            # Ensure it is world readable since Kaniko may be running as a different user
            _copy_or_chmod_tree(builddir)
        elif srcpath:
            _copy_or_chmod_tree(srcpath, builddir)
        else:
            raise ValueError("No fileobj or srcpath")

    def _run_external_kaniko(self, cmdargs):
        input = {
            "command": [self.kaniko_executable] + cmdargs,
            "credentials": [],
        }
        # Dict with fields
        # - registry
        # - Either username and password
        # - Or auth
        if self.registry_credentials:
            input["credentials"].append(self.registry_credentials)
        if self.cache_registry_credentials:
            input["credentials"].append(self.cache_registry_credentials)

        # Remove auth values in debug message
        debug_input = {
            **input,
            "credentials": [r["registry"] for r in input["credentials"]],
        }
        message = json.dumps(input) + "\n"
        log_debug(f"Sending {self.kaniko_address}: {debug_input}\n")
        self._s.sendall(message.encode())

        # Receive data
        last_chunk = ""
        while True:
            chunk = self._s.recv(1024000)
            if chunk:
                last_chunk = chunk.decode()
                yield last_chunk
            else:
                break

        self._s.close()
        if last_chunk != "status: SUCCESS\n":
            raise RuntimeError(f"Kaniko build failed: {last_chunk}")

    def build(
        self,
        *,
        buildargs=None,
        cache_from=None,
        container_limits=None,
        tag="",
        custom_context=False,
        dockerfile="",
        fileobj=None,
        path="",
        labels=None,
        platform=None,
        **kwargs,
    ):
        log_debug("kaniko executor")

        cmdargs = []

        bargs = buildargs or {}
        for k, v in bargs.items():
            cmdargs.extend(["--build-arg", "{}={}".format(k, v)])

        if cache_from:
            log_info(f"Ignoring cache_from={cache_from}")

        if container_limits:
            log_info(f"Ignoring container_limits={container_limits}")

        if tag:
            cmdargs.extend(["--destination", tag])

        if dockerfile:
            cmdargs.extend(["--dockerfile", dockerfile])

        if labels:
            for k, v in labels.items():
                cmdargs.extend(["--label", "{}={}".format(k, v)])

        if platform:
            cmdargs.extend(["--custom-platform", platform])

        # TODO: what to do with these?
        # for ignore in ("custom_context", "decode"):
        #     try:
        #         kwargs.pop(ignore)
        #     except KeyError:
        #         pass

        if kwargs:
            raise ValueError("Additional kwargs not supported")

        ## Kaniko specific args

        # Kaniko uses a registry as a cache
        if self.cache_registry:
            cache_registry_host = self.cache_registry.split("/")[0]
            cmdargs.extend(
                [
                    "--cache=true",
                    "--cache-copy-layers=true",
                    "--cache-run-layers=true",
                    f"--cache-repo={self.cache_registry}",
                ]
            )
            if self.cache_registry_credentials:
                cache_credentials = self.cache_registry_credentials.copy()
                if self.cache_registry_insecure:
                    cmdargs.append(f"--insecure-registry={cache_registry_host}")
                    cache_credentials["tls-verify=false"] = None
                if not cache_credentials.get("registry"):
                    cache_credentials["registry"] = cache_registry_host
                if not self._s:
                    self._login(**cache_credentials)

        if self.cache_dir:
            cmdargs.append(f"--cache-dir={self.cache_dir}")

        # Kaniko builds and pushes in one command
        if self.push_image:
            if self.registry_credentials and not self._s:
                self._login(**self.registry_credentials)
        else:
            cmdargs.append("--no-push")

        # Avoid try-except so that if build errors occur they don't result in a
        # confusing message about an exception whilst handling an exception
        if self.kaniko_address:
            builddir = mkdtemp(dir=self.kaniko_build_path)
            try:
                self._create_build_context(fileobj, path, builddir)
                cmdargs.extend(
                    ["--context", f"/workspace/{os.path.split(builddir)[1]}"]
                )
                for line in self._run_external_kaniko(cmdargs):
                    yield line
            finally:
                shutil.rmtree(builddir)
        else:
            builddir = mkdtemp()
            try:
                self._create_build_context(fileobj, path, builddir)
                cmdargs.extend(["--context", builddir])
                for line in exec_podman_stream(cmdargs, exe=self.kaniko_executable):
                    yield line
            finally:
                shutil.rmtree(builddir)

    def images(self):
        log_debug("kaniko images not supported")
        return []

    def inspect_image(self, image):
        raise NotImplementedError("kaniko inspect_image not supported")

    def _login(self, **kwargs):
        # kaniko doesn't support login, docker CLI doesn't support insecure, so use skopeo
        args = ["login"]

        registry = None
        password = None
        authfile = None

        for k, v in kwargs.items():
            if k == "password":
                password = v
            elif k == "registry":
                registry = v
            elif v is None:
                args.append(f"--{k}")
            else:
                args.append(f"--{k}={v}")

        if password is not None:
            args.append("--password-stdin")

        if authfile is None:
            authfile = os.path.join(os.path.expanduser("~"), ".docker", "config")
        args.append(f"--authfile={authfile}")

        if registry is not None:
            args.append(registry)

        log_debug(f"{self.login_executable} login to registry {registry}")
        podman_kwargs = {"capture": "both"}
        if password is not None:
            podman_kwargs["input"] = password
        o = exec_podman(args, exe=self.login_executable, **podman_kwargs)
        log_debug(o)

    def push(self, image_spec):
        if not self.push_image:
            raise ValueError("Image must be pushed by setting push_image=True")
        # Otherwise should already have pushed as part of build
        return []

    def run(
        self,
        *args,
        **kwargs,
    ):
        raise NotImplementedError("kaniko run not supported")
