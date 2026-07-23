import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pytest_kind import KindCluster
from pytest_kind import KindToolError
from pytest_kind.cluster import KIND_VERSION
from pytest_kind.cluster import KUBECTL_VERSION


def test_cluster_name():
    cluster = KindCluster("foo")
    assert cluster.name == "foo"


def test_cluster_kubeconfig():
    path = Path("/tmp/test.yaml")
    cluster = KindCluster("foo", path)
    assert cluster.kubeconfig_path == path


def test_create_delete():
    cluster = KindCluster("pytest-kind-test-create-delete")
    try:
        cluster.create()
    finally:
        cluster.delete()


@pytest.mark.parametrize(
    "machine, expected",
    [
        ("x86_64", "amd64"),
        ("AMD64", "amd64"),
        ("aarch64", "arm64"),
        ("arm64", "arm64"),
    ],
)
def test_cluster_architecture(monkeypatch, tmp_path, machine, expected):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pytest_kind.cluster.platform.machine", lambda: machine)

    cluster = KindCluster("architecture")

    assert cluster.architecture == expected


def test_arm64_download_urls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pytest_kind.cluster.platform.system", lambda: "Linux")
    monkeypatch.setattr("pytest_kind.cluster.platform.machine", lambda: "aarch64")
    cluster = KindCluster("arm64")
    downloads = []

    def download(url, destination):
        downloads.append(url)
        destination.touch()

    monkeypatch.setattr(cluster, "_download", download)
    monkeypatch.setattr(
        cluster,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    cluster.ensure_kind()
    cluster.ensure_kubectl()

    assert downloads == [
        f"https://github.com/kubernetes-sigs/kind/releases/download/{KIND_VERSION}/kind-linux-arm64",
        f"https://dl.k8s.io/release/{KUBECTL_VERSION}/bin/linux/arm64/kubectl",
    ]


def test_unsupported_architecture_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pytest_kind.cluster.platform.machine", lambda: "riscv64")
    cluster = KindCluster("unsupported")

    with pytest.raises(RuntimeError, match="--kind-bin and --kind-kubectl-bin"):
        cluster.ensure_kind()


def test_kubectl_failure_includes_command_output(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    kubectl = tmp_path / "kubectl"
    kubectl.touch()
    cluster = KindCluster("failure", kubectl_path=kubectl)
    error = subprocess.CalledProcessError(
        1,
        [str(kubectl), "get", "pods"],
        output="partial output",
        stderr="connection refused",
    )
    monkeypatch.setattr("pytest_kind.cluster.subprocess.run", Mock(side_effect=error))

    with pytest.raises(KindToolError) as exc_info:
        cluster.kubectl("get", "pods")

    message = str(exc_info.value)
    assert "kubectl command failed with exit code 1" in message
    assert "get pods" in message
    assert "partial output" in message
    assert "connection refused" in message


def test_execution_error_identifies_platform_and_architecture(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pytest_kind.cluster.platform.machine", lambda: "x86_64")
    kubectl = tmp_path / "kubectl"
    kubectl.touch()
    cluster = KindCluster("failure", kubectl_path=kubectl)
    monkeypatch.setattr(
        "pytest_kind.cluster.subprocess.run",
        Mock(side_effect=OSError(8, "Exec format error")),
    )

    with pytest.raises(KindToolError) as exc_info:
        cluster.kubectl("version")

    message = str(exc_info.value)
    assert "platform=linux, architecture=amd64" in message
    assert "Exec format error" in message
    assert "--kind-kubectl-bin" in message
