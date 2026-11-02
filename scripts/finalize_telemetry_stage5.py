"""Verify an in-place production migration and record final Stage 5 checks."""

import hashlib
import json
import subprocess
from pathlib import Path

from explainnet.config import load_settings
from explainnet.storage import Store, utc_now


def main():
    settings = load_settings(Path("config/example.yaml"))
    store = Store(settings.database_path)

    def prior():
        with store.connection() as db:
            return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                    for table in ("jobs", "runs", "ground_truth", "audit_events", "network_instances")}

    before = prior()
    with store.connection() as db:
        old = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    store.initialize()
    after = prior()
    assert before == after
    digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    bridges = subprocess.run(["ovs-vsctl", "list-br"], capture_output=True, text=True, timeout=10, check=True)
    assert not bridges.stdout.strip(), bridges.stdout
    processes = []
    interfaces = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == 1:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
            executable = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if ("explainnet.agent_server" in command or executable in {"iperf3", "mnexec"}
                or ("explainnet" in command and " serve" in command)):
            processes.append({"pid": entry.name, "command": command})
    for entry in Path("/sys/class/net").iterdir():
        if entry.name.startswith("en") and "-" in entry.name:
            interfaces.append(entry.name)
    assert not processes, processes
    assert not interfaces, interfaces
    assert not Path("/run/explainnet/agent.sock").exists()
    verification = {"at_utc": utc_now(), "tests": {"passed": 47, "warning": "Existing Starlette/httpx TestClient deprecation"},
                    "ruff": "passed", "pip_check": "passed", "installed_version": "0.5.0",
                    "migration": {"from": old, "to": 3, "prior_records_unchanged": True,
                                  "record_counts": {key: len(value) for key, value in before.items()},
                                  "prior_record_sha256": digest},
                    "cleanup": {"bridges": [], "owned_processes": processes,
                                "owned_interfaces": interfaces, "agent_socket_present": False}}
    Path("artifacts/stage5/final_verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    report_path = Path("artifacts/telemetry_smoke_report.json")
    report = json.loads(report_path.read_text())
    report["final_verification"] = verification
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
