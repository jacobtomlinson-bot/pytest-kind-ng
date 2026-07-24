import subprocess
import sys
from pathlib import Path

import pytest

from pytest_kind import KindCluster
from pytest_kind import KindToolError


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


def test_ensure_tools(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cluster = KindCluster("ensure-tools")

    cluster.ensure_kind()
    cluster.ensure_kubectl()

    assert cluster.kind_path.is_file()
    assert cluster.kubectl_path.is_file()
    subprocess.run([cluster.kind_path, "version"], check=True)
    subprocess.run([cluster.kubectl_path, "version", "--client"], check=True)


def test_kubectl_failure_includes_command_output(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cluster = KindCluster("failure", kubectl_path=Path(sys.executable))
    command = (
        "import sys; "
        "print('partial output'); "
        "print('connection refused', file=sys.stderr); "
        "sys.exit(1)"
    )

    with pytest.raises(KindToolError) as exc_info:
        cluster.kubectl("-c", command)

    message = str(exc_info.value)
    assert "kubectl command failed with exit code 1" in message
    assert "partial output" in message
    assert "connection refused" in message
