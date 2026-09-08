import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def mac():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mac.py"
    spec = importlib.util.spec_from_file_location("mac_deployment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unload_waits_for_service_removal(mac, monkeypatch):
    state = {"registered": True, "remaining_probes": 2}

    def run(command, **kwargs):
        if command[1] == "print":
            state["remaining_probes"] -= 1
            state["registered"] = state["remaining_probes"] > 0
            return SimpleNamespace(returncode=0 if state["registered"] else 113)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(mac.subprocess, "run", run)
    mac.unload_agent("tunnel")
    assert not state["registered"], "bootout returns before a slow service has been removed"


def test_unload_reports_a_service_that_never_stops(mac, monkeypatch):
    monkeypatch.setattr(mac.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    clock = iter((0, 31))
    monkeypatch.setattr(mac.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="finish unloading"):
        mac.unload_agent("tunnel")
