"""Stage 3 unit tests; runtime doubles below do not prove packet delivery."""

import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from explainnet.agent import AgentRequest
from explainnet.config import load_network, load_profiles
from explainnet.network_contracts import NetworkDefinition, WorkloadProfile
from explainnet.network_runtime import NetworkManager
from explainnet.topology.spec import host_routes, validate_profile

ROOT = Path(__file__).resolve().parents[1]


def small_definition():
    raw = load_network(ROOT / "config" / "topology.yaml").model_dump()
    raw["switches"] = ["s1"]
    raw["hosts"] = [dict(h, switch_id="s1") for h in raw["hosts"][:2]]
    raw["links"] = []
    raw["pairs"] = []
    return raw


def test_config_validation_paths_and_baseline():
    definition = load_network(ROOT / "config" / "topology.yaml")
    raw = definition.model_dump()
    primary = host_routes(raw, {"critical": "primary", "bulk": "primary"})
    alternate = host_routes(raw, {"critical": "alternative", "bulk": "primary"})
    assert next(r for r in primary if r["pair_id"] == "critical")["switches"] == ["s1", "s2", "s3", "s5"]
    assert next(r for r in alternate if r["pair_id"] == "critical")["switches"] == ["s1", "s4", "s5"]
    assert next(r for r in alternate if r["pair_id"] == "bulk")["switches"] == ["s1", "s2", "s3", "s5"]
    assert len(primary) == 15
    profiles = load_profiles(ROOT / "config" / "traffic.yaml")
    assert sum(profiles[name].offered_bps for name in ("critical", "bulk")) < 20000000 / 2
    for profile in profiles.values():
        validate_profile(profile.model_dump(), raw)
    for change in ("capacity", "cycle", "host", "version"):
        invalid = deepcopy(raw)
        if change == "capacity":
            invalid["links"][0]["forward_bps"] = -1
        elif change == "cycle":
            invalid["pairs"][0]["paths"]["primary"] = ["s1", "s2", "s1", "s4", "s5"]
        elif change == "host":
            invalid["hosts"][0]["switch_id"] = "s8"
        else:
            invalid["schema_version"] = 2
        with pytest.raises(ValidationError):
            NetworkDefinition.model_validate(invalid)
    with pytest.raises(ValidationError):
        WorkloadProfile(profile_id="p1", source_host="h1", target_host="h3", protocol="tcp",
                        offered_bps=0, duration_s=99)


def test_agent_rejects_unrestricted_and_invalid_instance_requests():
    with pytest.raises(ValidationError):
        AgentRequest(operation="network_cleanup", parameters={"schema_version": 1, "instance_id": "../../other"})
    with pytest.raises(ValidationError):
        AgentRequest(operation="shell", parameters={"command": "anything"})
    with pytest.raises(ValidationError):
        AgentRequest(operation="network_start", parameters={"schema_version": 1, "instance_id": "p1", "definition": {}})


def test_stale_ownership_is_not_live_or_blindly_deleted(tmp_path, monkeypatch):
    record = {"instance_id": "old1", "state": "running", "token": "abc123", "bridges": ["enabc123s1"],
              "host_processes": [], "traffic_processes": [], "root_interfaces": []}
    (tmp_path / "instance_old1.json").write_text(json.dumps(record))
    calls = []
    def fake_command(*args, **kwargs):
        calls.append(args)
        if "list-br" in args:
            return "enabc123s1"
        return json.dumps({'headings':['name','external_ids'], 'data':[['enabc123s1',
            ['map', [['explainnet_instance','someone_else'], ['explainnet_token','different_owner']]]]]})
    monkeypatch.setattr("explainnet.network_runtime.command", fake_command)
    manager = NetworkManager(tmp_path)
    try:
        assert manager.inspect("old1")["state"] == "failed"
        assert manager.inspect("old1")["live_verified"] is False
        with pytest.raises(ValueError, match="ownership mismatch"):
            manager.cleanup("old1")
        assert not any("del-br" in args for args in calls)
        assert manager.stop("unknown1")["state"] == "stopped"
        with pytest.raises(BlockingIOError):
            NetworkManager(tmp_path)
    finally:
        manager.shutdown()


def test_partial_startup_failure_cleans_only_its_net(tmp_path, monkeypatch):
    stopped = []
    class FakeNet:
        def __init__(self, **kwargs):
            pass
        def addSwitch(self, *args, **kwargs):
            raise RuntimeError("controlled startup failure")
        def stop(self):
            stopped.append(True)
    modules = {"mininet": types.ModuleType("mininet"), "mininet.net": types.ModuleType("mininet.net"),
               "mininet.node": types.ModuleType("mininet.node"), "mininet.link": types.ModuleType("mininet.link")}
    modules["mininet.net"].Mininet = FakeNet
    modules["mininet.node"].OVSSwitch = type("FakeSwitch", (), {})
    modules["mininet.link"].TCLink = type("FakeLink", (), {})
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("explainnet.network_runtime.command", lambda *args, **kwargs: "[]" if args[0] == "ip" else "")
    manager = NetworkManager(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="controlled"):
            manager.start("broken1", small_definition())
        assert stopped == [True]
        assert manager.records["broken1"]["state"] == "failed"
        assert not manager.instances
    finally:
        manager.shutdown()
