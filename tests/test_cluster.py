import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError

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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="downloaded test executable uses a POSIX shell script",
)
def test_ensure_kind_retries_transient_download_error(
    monkeypatch, tmp_path, http_server, retry_delays
):
    monkeypatch.chdir(tmp_path)
    executable = b"#!/bin/sh\nexit 0\n"
    http_server.push(503)
    http_server.push(200, executable)
    monkeypatch.setenv("KIND_DOWNLOAD_URL", f"{http_server.url}/kind")
    cluster = KindCluster("download-retry")

    cluster.ensure_kind()

    assert cluster.kind_path.read_bytes() == executable
    assert http_server.requests == ["/kind", "/kind"]
    assert retry_delays == [1]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="downloaded test executable uses a POSIX shell script",
)
def test_ensure_kind_retries_interrupted_download(
    monkeypatch, tmp_path, http_server, retry_delays
):
    monkeypatch.chdir(tmp_path)
    executable = b"#!/bin/sh\nexit 0\n"
    partial = b"partial"
    http_server.push(200, partial, content_length=len(partial) + 1)
    http_server.push(200, executable)
    monkeypatch.setenv("KIND_DOWNLOAD_URL", f"{http_server.url}/kind")
    cluster = KindCluster("interrupted-download")

    cluster.ensure_kind()

    assert cluster.kind_path.read_bytes() == executable
    assert http_server.requests == ["/kind", "/kind"]
    assert retry_delays == [1]


def test_ensure_kind_does_not_retry_permanent_http_error(
    monkeypatch, tmp_path, http_server, retry_delays
):
    monkeypatch.chdir(tmp_path)
    http_server.push(404)
    http_server.push(200, b"not used")
    monkeypatch.setenv("KIND_DOWNLOAD_URL", f"{http_server.url}/missing")
    cluster = KindCluster("download-not-found")

    with pytest.raises(HTTPError):
        cluster.ensure_kind()

    assert not cluster.kind_path.exists()
    assert http_server.requests == ["/missing"]
    assert retry_delays == []


def test_ensure_kind_cleans_up_after_exhausted_retries(
    monkeypatch, tmp_path, http_server, retry_delays
):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        http_server.push(503)
    monkeypatch.setenv("KIND_DOWNLOAD_URL", f"{http_server.url}/unavailable")
    cluster = KindCluster("download-exhausted")
    tmp_file = cluster.kind_path.with_suffix(cluster.kind_path.suffix + ".tmp")

    with pytest.raises(HTTPError):
        cluster.ensure_kind()

    assert not cluster.kind_path.exists()
    assert not tmp_file.exists()
    assert http_server.requests == ["/unavailable"] * 3
    assert retry_delays == [1, 2]


def test_ensure_kind_rejects_non_http_download(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "kind"
    source.write_bytes(b"not used")
    monkeypatch.setenv("KIND_DOWNLOAD_URL", source.as_uri())
    cluster = KindCluster("unsupported-download-scheme")

    with pytest.raises(ValueError, match="Unsupported download URL scheme 'file'"):
        cluster.ensure_kind()

    assert not cluster.kind_path.exists()


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
