import subprocess
from types import SimpleNamespace

import pytest

from pytest_kind.plugin import kind_cluster


@pytest.mark.parametrize(
    ("created", "keep", "deleted"),
    [
        (False, False, False),
        (True, False, True),
        (True, True, False),
    ],
)
def test_kind_cluster_only_deletes_clusters_it_created(
    monkeypatch, created, keep, deleted
):
    class FakeKindCluster:
        def __init__(self, *args, **kwargs):
            self.deleted = False

        def create(self):
            return created

        def delete(self):
            self.deleted = True

    options = {
        "cluster_name": "reused",
        "keep_cluster": keep,
        "kubeconfig": None,
        "kind_image": None,
        "kind_bin": None,
        "kind_kubectl_bin": None,
    }
    request = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda option: options[option])
    )
    monkeypatch.setattr("pytest_kind.plugin.KindCluster", FakeKindCluster)

    fixture = kind_cluster.__wrapped__(request)
    cluster = next(fixture)
    with pytest.raises(StopIteration):
        next(fixture)

    assert cluster.deleted is deleted


def test_kind_cluster(testdir):
    testdir.makepyfile(
        """
    import socket

    import kr8s

    def test_cluster_api(kind_cluster):
        api = kr8s.api(kubeconfig=kind_cluster.kubeconfig_path)
        version = api.version()
        assert version["major"] == "1"
        assert version["minor"] == "35"

    def test_kubectl_version(kind_cluster):
        assert "v1.36" in kind_cluster.kubectl("version")

    def test_load_docker_image(kind_cluster):
        kind_cluster.load_docker_image("busybox")

    def test_port_forward(kind_cluster):
        kind_cluster.kubectl("rollout", "status", "deploy/coredns", "-n", "kube-system")

        # high number of retries as pod is pending for a while..
        with kind_cluster.port_forward("service/kube-dns", 53, "-n", "kube-system", retries=20) as port:
            assert port >= 1024
            s = socket.socket()
            try:
                s.connect(('127.0.0.1', port))
            finally:
                s.close()
    """
    )

    subprocess.run(["docker", "pull", "busybox"], check=True)

    result = testdir.runpytest("--cluster-name", "pytest-kind-test-plugin")
    result.assert_outcomes(passed=4)
