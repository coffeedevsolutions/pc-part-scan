"""The store backend must be file-based unless MongoDB is configured."""

import importlib
import sys


def _fresh_backend(monkeypatch, **env):
    for k in ("MONGODB_URI", "PCPS_STORE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for name in [n for n in sys.modules if n.startswith("pcpartscan")]:
        del sys.modules[name]
    return importlib.import_module("pcpartscan.store").backend


def test_defaults_to_files(monkeypatch):
    be = _fresh_backend(monkeypatch)
    assert be.__name__ == "pcpartscan.dataset"


def test_uri_selects_mongo(monkeypatch):
    be = _fresh_backend(monkeypatch, MONGODB_URI="mongodb+srv://x:y@example.invalid/")
    assert be.__name__ == "pcpartscan.store.mongo"


def test_files_override_wins(monkeypatch):
    be = _fresh_backend(monkeypatch,
                        MONGODB_URI="mongodb+srv://x:y@example.invalid/",
                        PCPS_STORE="files")
    assert be.__name__ == "pcpartscan.dataset"
