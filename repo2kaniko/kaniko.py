# Use Kaniko instead of Docker
import json
import os
import tarfile
from tempfile import TemporaryDirectory
from traitlets import default, Bool, Dict, Unicode

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


class KanikoEngine(ContainerEngine):
    """
    Kaniko build engine
    """

    kaniko_executable = Unicode(
        "/kaniko/executor",
        help="The kaniko executable to use for all commands.",
        config=True,
    )

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

        lines = exec_podman(["version"], capture="stdout", exe=self.kaniko_executable)
        log_debug(lines)

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
                self._login(**cache_credentials)

        if self.cache_dir:
            cmdargs.append(f"--cache-dir={self.cache_dir}")

        # Kaniko builds and pushes in one command
        if self.push_image:
            if self.registry_credentials:
                self._login(**self.registry_credentials)
        else:
            cmdargs.append("--no-push")

        # Avoid try-except so that if build errors occur they don't result in a
        # confusing message about an exception whilst handling an exception
        if fileobj:
            with TemporaryDirectory() as builddir:
                cmdargs.extend(["--context", builddir])
                tarf = tarfile.open(fileobj=fileobj)
                tarf.extractall(builddir)
                log_debug(builddir)

                lines = execute_cmd(["ls", "-lRa", builddir], capture="stdout")
                log_debug(lines)
                for line in exec_podman_stream(cmdargs, exe=self.kaniko_executable):
                    yield line
        else:
            builddir = path
            assert path
            cmdargs.extend(["--context", builddir])
            for line in exec_podman_stream(cmdargs, exe=self.kaniko_executable):
                yield line

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
            authfile = os.path.expanduser("~/.docker/config.json")
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
