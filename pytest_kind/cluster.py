import logging
import os
import platform
import random
import shlex
import shutil
import socket
import ssl
import subprocess
import time
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from typing import Generator
from typing import Optional
from typing import Union
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import urlopen

import pykube


KIND_VERSION = os.environ.get("KIND_VERSION", "v0.31.0")
KUBECTL_VERSION = os.environ.get("KUBECTL_VERSION", "v1.36.1")

DOWNLOAD_RETRIES = 2
DOWNLOAD_TIMEOUT = 60

ARCHITECTURES = {
    "aarch64": "arm64",
    "amd64": "amd64",
    "arm64": "arm64",
    "x86_64": "amd64",
}


class KindToolError(RuntimeError):

    """Raised when a kind or kubectl command cannot be executed."""


def _architecture(machine: str) -> str:
    try:
        return ARCHITECTURES[machine.lower()]
    except KeyError:
        supported = ", ".join(sorted(ARCHITECTURES))
        raise RuntimeError(
            f"Unsupported machine architecture {machine!r}. "
            f"Supported architecture names are: {supported}. "
            "Provide local binaries with --kind-bin and --kind-kubectl-bin."
        ) from None


def _retryable_download_error(error: Exception) -> bool:
    if not isinstance(error, HTTPError):
        return True
    return error.code in (408, 429) or 500 <= error.code < 600


class KindCluster:
    def __init__(
        self,
        name: str,
        kubeconfig: Optional[Path] = None,
        image: Optional[str] = None,
        kind_path: Optional[Path] = None,
        kubectl_path: Optional[Path] = None,
    ):
        self.name = name
        self.image = image
        path = Path(".pytest-kind")
        self.path = path / name
        self.path.mkdir(parents=True, exist_ok=True)
        self.kubeconfig_path = kubeconfig or (self.path / "kubeconfig")
        self.platform = platform.system().lower()
        self.machine = platform.machine()
        suffix = ".exe" if self.platform == "windows" else ""
        self.kind_path = kind_path or (self.path / f"kind-{KIND_VERSION}{suffix}")
        self.kubectl_path = kubectl_path or (
            self.path / f"kubectl-{KUBECTL_VERSION}{suffix}"
        )

    @property
    def architecture(self) -> str:
        """Return the tool-download architecture for the current machine."""
        return _architecture(self.machine)

    def _run(
        self, tool: str, executable: Path, *args: str, **kwargs
    ) -> subprocess.CompletedProcess:
        command = [str(executable), *args]
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("encoding", "utf-8")
        kwargs["check"] = True
        try:
            return subprocess.run(command, **kwargs)
        except subprocess.CalledProcessError as ex:
            details = []
            if ex.stdout:
                details.append(f"stdout:\n{ex.stdout.rstrip()}")
            if ex.stderr:
                details.append(f"stderr:\n{ex.stderr.rstrip()}")
            diagnostic = "\n".join(details) or "No command output was captured."
            raise KindToolError(
                f"{tool} command failed with exit code {ex.returncode}.\n"
                f"Command: {shlex.join(command)}\n{diagnostic}"
            ) from ex
        except OSError as ex:
            option = "--kind-bin" if tool == "kind" else "--kind-kubectl-bin"
            raise KindToolError(
                f"Could not execute {tool} at {executable} "
                f"(platform={self.platform}, architecture={self.architecture}): {ex}. "
                "The binary may be corrupt or built for a different platform. "
                f"Delete the cached binary and retry, or use {option}."
            ) from ex

    def _download(self, url: str, destination: Path) -> None:
        tmp_file = destination.with_suffix(destination.suffix + ".tmp")
        try:
            for attempt in range(DOWNLOAD_RETRIES + 1):
                logging.info(
                    f"Downloading {url} "
                    f"(attempt {attempt + 1}/{DOWNLOAD_RETRIES + 1}).."
                )
                try:
                    with urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
                        with tmp_file.open("wb") as fd:
                            shutil.copyfileobj(response, fd)
                    break
                except (
                    HTTPException,
                    URLError,
                    ConnectionError,
                    TimeoutError,
                    socket.timeout,
                    ssl.SSLError,
                ) as ex:
                    tmp_file.unlink(missing_ok=True)
                    if not _retryable_download_error(ex) or attempt == DOWNLOAD_RETRIES:
                        raise
                    delay = 2**attempt
                    logging.warning(
                        f"Download failed: {ex}. Retrying in {delay} second(s).."
                    )
                    time.sleep(delay)
            tmp_file.chmod(0o755)
            tmp_file.replace(destination)
        finally:
            tmp_file.unlink(missing_ok=True)

    def ensure_kind(self):
        if not self.kind_path.exists():
            url = os.getenv(
                "KIND_DOWNLOAD_URL",
                f"https://github.com/kubernetes-sigs/kind/releases/download/{KIND_VERSION}/kind-{self.platform}-{self.architecture}",
            )
            self._download(url, self.kind_path)
            try:
                self._run("kind", self.kind_path, "version")
            except KindToolError:
                self.kind_path.unlink()
                raise

    def ensure_kubectl(self):
        if not self.kubectl_path.exists():
            executable = "kubectl.exe" if self.platform == "windows" else "kubectl"
            url = os.getenv(
                "KUBECTL_DOWNLOAD_URL",
                f"https://dl.k8s.io/release/{KUBECTL_VERSION}/bin/{self.platform}/{self.architecture}/{executable}",
            )
            self._download(url, self.kubectl_path)
            try:
                self._run("kubectl", self.kubectl_path, "version", "--client")
            except KindToolError:
                self.kubectl_path.unlink()
                raise

    def create(self, config_file: Optional[Union[str, Path]] = None):
        """Create the kind cluster if it does not exist (otherwise re-use)."""
        self.ensure_kind()

        self.kubeconfig_path.touch(0o600, exist_ok=True)

        cluster_exists = False

        while not cluster_exists:
            out = self._run("kind", self.kind_path, "get", "clusters").stdout
            for name in out.splitlines():
                if name == self.name:
                    cluster_exists = True

            if not cluster_exists:
                create_cmd = [
                    str(self.kind_path),
                    "create",
                    "cluster",
                    f"--name={self.name}",
                    f"--kubeconfig={self.kubeconfig_path}",
                ]

                if self.image:
                    create_cmd += [
                        f"--image={self.image}",
                    ]

                if config_file:
                    create_cmd += ["--config", str(config_file)]

                logging.info(f"Creating cluster {self.name}..")
                self._run("kind", self.kind_path, *create_cmd[1:])
                cluster_exists = True

            if not self.kubeconfig_path.exists():
                self.delete()
                cluster_exists = False

        config = pykube.KubeConfig.from_file(self.kubeconfig_path)
        self.api = pykube.HTTPClient(config)

    def load_docker_image(self, docker_image: str):
        logging.info(f"Loading Docker image {docker_image} in cluster (usually ~5s)..")
        self._run(
            "kind",
            self.kind_path,
            "load",
            "docker-image",
            "--name",
            self.name,
            docker_image,
        )

    def kubectl(self, *args: str, **kwargs) -> str:
        """Run a kubectl command against the cluster and return the output as string."""
        self.ensure_kubectl()
        return self._run(
            "kubectl",
            self.kubectl_path,
            *args,
            env={**os.environ, "KUBECONFIG": str(self.kubeconfig_path)},
            **kwargs,
        ).stdout

    @contextmanager
    def port_forward(
        self,
        service_or_pod_name: str,
        remote_port: int,
        *args,
        local_port: Optional[int] = None,
        retries: int = 10,
    ) -> Generator[int, None, None]:
        """Run "kubectl port-forward" for the given service/pod and use a random local port."""
        self.ensure_kubectl()
        port_to_use: int
        proc = None
        for i in range(retries):
            if proc:
                proc.kill()
            # Linux epheremal port range starts at 32k
            port_to_use = local_port or random.randrange(5000, 30000)
            proc = subprocess.Popen(
                [
                    str(self.kubectl_path),
                    "port-forward",
                    service_or_pod_name,
                    f"{port_to_use}:{remote_port}",
                    *args,
                ],
                env={**os.environ, "KUBECONFIG": str(self.kubeconfig_path)},
            )
            time.sleep(1)
            returncode = proc.poll()
            if returncode is not None:
                if i >= retries - 1:
                    raise Exception(
                        f"kubectl port-forward returned exit code {returncode}"
                    )
                else:
                    # try again
                    continue
            s = socket.socket()
            try:
                s.connect(("127.0.0.1", port_to_use))
            except:
                if i >= retries - 1:
                    raise
            finally:
                s.close()
        try:
            yield port_to_use
        finally:
            if proc:
                proc.kill()

    def delete(self):
        """Delete the kind cluster ("kind delete cluster")."""
        logging.info(f"Deleting cluster {self.name}..")
        self._run(
            "kind",
            self.kind_path,
            "delete",
            "cluster",
            f"--name={self.name}",
            f"--kubeconfig={self.kubeconfig_path}",
        )
