import importlib
import sys

import pytest_kind


def test_version():
    assert pytest_kind.__version__ != "unknown"


def test_version_fallback(monkeypatch):
    with monkeypatch.context() as context:
        context.setitem(sys.modules, "pytest_kind._version", None)
        package = importlib.reload(pytest_kind)
        assert package.__version__ == "unknown"

    importlib.reload(pytest_kind)
