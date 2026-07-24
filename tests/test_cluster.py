import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from pytest_kind import KindCluster
from pytest_kind import KindToolError
from pytest_kind.cluster import DOWNLOAD_TIMEOUT


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


def test_download_retries_transient_request_failure(monkeypatch, tmp_path):
    cluster = KindCluster("download-retry")
    destination = tmp_path / "kubectl"
    response = Mock()
    response.iter_content.return_value = [b"downloaded"]
    attempts = []

    def get(url, **kwargs):
        attempts.append((url, kwargs))
        if len(attempts) == 1:
            raise requests.exceptions.SSLError("TLS connection closed")
        return response

    monkeypatch.setattr(requests, "get", get)
    sleep = Mock()
    monkeypatch.setattr("pytest_kind.cluster.time.sleep", sleep)

    cluster._download("https://example.com/kubectl", destination)

    assert destination.read_bytes() == b"downloaded"
    assert attempts == [
        (
            "https://example.com/kubectl",
            {"stream": True, "timeout": DOWNLOAD_TIMEOUT},
        ),
        (
            "https://example.com/kubectl",
            {"stream": True, "timeout": DOWNLOAD_TIMEOUT},
        ),
    ]
    sleep.assert_called_once_with(1)
    response.close.assert_called_once_with()


def test_download_does_not_retry_permanent_http_error(monkeypatch, tmp_path):
    cluster = KindCluster("download-not-found")
    destination = tmp_path / "kubectl"
    response = Mock(status_code=404)
    error = requests.exceptions.HTTPError("not found", response=response)
    response.raise_for_status.side_effect = error
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    sleep = Mock()
    monkeypatch.setattr("pytest_kind.cluster.time.sleep", sleep)

    with pytest.raises(requests.exceptions.HTTPError):
        cluster._download("https://example.com/missing", destination)

    get.assert_called_once_with(
        "https://example.com/missing",
        stream=True,
        timeout=DOWNLOAD_TIMEOUT,
    )
    sleep.assert_not_called()
    response.close.assert_called_once_with()


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
