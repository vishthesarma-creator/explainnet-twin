"""Stdlib-only privileged agent. Launch with OS Python, not the app venv."""

import argparse
import json
import os
import pwd
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import threading
import weakref
from pathlib import Path

from explainnet.agent_protocol import OPERATIONS, validate_parameters
from explainnet.response_evidence import FRAME_LIMIT, READ_OPERATIONS, EvidenceFiles

RPC_LOCK = threading.RLock()
RPC_WORKERS = weakref.WeakValueDictionary()


def dispatch_v2(request, manager):
    """A duplicate/unknown control RPC never repeats a physical mutation."""
    import hashlib

    from explainnet.response_evidence import encoded
    # Validate before using the request ID in a filename.
    rid = request.get('request_id', '')
    if not isinstance(rid, str) or len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
        raise ValueError('invalid request ID')
    op = request['operation']
    evidence = EvidenceFiles(manager.state_dir / 'response_evidence')
    if op == 'evidence_read':
        return dispatch(request, manager)
    if op in READ_OPERATIONS:
        return evidence.acknowledgement(op, dispatch(request, manager))
    with RPC_LOCK:
        operation_lock = RPC_WORKERS.setdefault(rid, threading.RLock())
    with operation_lock:
        directory = manager.state_dir / 'rpc_receipts'
        directory.mkdir(exist_ok=True)
        path = directory / (rid + '.json')
        fingerprint = hashlib.sha256(encoded(request)).hexdigest()
        if path.exists():
            prior = json.loads(path.read_text())
            if prior['request_hash'] != fingerprint:
                raise ValueError('request identity reused with different inputs')
            if prior['state'] != 'completed':
                raise RuntimeError('previous RPC outcome unknown; reconcile owned state, no mutation replayed')
            return prior['ack']
        # Validation happens before creating an intent, but no mutation precedes it.
        validate_parameters(op, request.get('parameters', {}))
        intent = {'request_hash': fingerprint, 'state': 'pending', 'operation': op}
        def save(value):
            tmp = path.with_suffix('.tmp')
            with tmp.open('w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            tmp.replace(path)
        save(intent)
        data = dispatch(request, manager)
        ack = evidence.acknowledgement(op, data)
        save(intent | {'state': 'completed', 'ack': ack})
        return ack


def checked(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=3, check=True).stdout.strip()


def dispatch(request: object, manager=None) -> dict:
    if not isinstance(request, dict) or not {"protocol_version", "request_id", "operation"} <= set(request) or set(request) - {"protocol_version", "request_id", "operation", "parameters"}:
        raise ValueError("invalid request fields")
    if type(request['protocol_version']) is not int or request["protocol_version"] not in {1, 2} or not isinstance(request["request_id"], str):
        raise ValueError("invalid protocol version or request ID")
    if len(request["request_id"]) != 32 or any(c not in "0123456789abcdef" for c in request["request_id"]):
        raise ValueError("invalid request ID")
    operation = request["operation"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError("unsupported operation")
    parameters = request.get("parameters", {})
    validate_parameters(operation, parameters)
    if operation == 'evidence_read':
        return EvidenceFiles(manager.state_dir / 'response_evidence').page(**parameters)
    if operation == "health":
        checked("ovs-vsctl", "list-br")
        checked("/usr/bin/python3", "-c", "import mininet")
        checked("tc", "-V")
        return {"status": "available", "agent_version": 2, 'protocol_versions': [1, 2]}
    if operation == "capabilities":
        return {
            "mininet_python": subprocess.run(["/usr/bin/python3", "-c", "import mininet"],
                                             capture_output=True, timeout=3, check=False).returncode == 0,
            "ovs": checked("ovs-vsctl", "--version").splitlines()[0],
            "tc": checked("tc", "-V"),
            "operations": sorted(OPERATIONS),
            "mutations_available": manager is not None,
            "unsupported": ["external_network_repair", "unqualified_original_action_families"],
        }
    if operation == "inventory" and manager is not None:
        return manager.inventory()
    if operation not in {"inventory", "health", "capabilities"}:
        if manager is None:
            raise ValueError("network owner is unavailable")
        args = {k: v for k, v in parameters.items() if k != "schema_version"}
        methods = {
            "network_start": manager.start, "network_inspect": manager.inspect, "network_stop": manager.stop,
            "network_cleanup": manager.cleanup, "path_select": manager.select_path, "network_probe": manager.probe,
            "traffic_start": manager.traffic_start, "traffic_status": manager.traffic_status, "traffic_stop": manager.traffic_stop,
            "scenario_start": manager.scenarios.start, "scenario_inspect": manager.scenarios.inspect,
            "scenario_stop": manager.scenarios.reset, "scenario_reset": manager.scenarios.reset,
        }
        if operation.startswith("lab_"):
            return getattr(manager.lab_actions, operation[4:])(**args)
        if operation in {"network_stop", "network_cleanup", "traffic_start", "traffic_stop", "scenario_start", "scenario_stop", "scenario_reset"}:
            manager.lab_actions.guard(args["instance_id"])
        if operation == "telemetry_observe":
            from explainnet.telemetry_observe import observe
            return observe(manager, **args)
        if operation.startswith('twin_'):
            return getattr(manager.twins, operation[5:])(**args)
        return methods[operation](**args)
    bridges = checked("ovs-vsctl", "list-br").splitlines()
    return {"bridges": [name for name in bridges if name.startswith("en-")]}


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(10)
        creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        if uid not in self.server.allowed_uids:
            return
        request_id = None
        try:
            line = self.rfile.readline(262145)
            if len(line) > 262144 or not line.endswith(b"\n"):
                raise ValueError("request too large or incomplete")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise TypeError('request must be an object')
            request_id = request.get("request_id") if isinstance(request, dict) else None
            data = dispatch_v2(request, self.server.network_manager) if request.get('protocol_version') == 2 else dispatch(request, self.server.network_manager)
            version = request['protocol_version']
            response = {"protocol_version": version, "request_id": request_id, "ok": True, "data": data}
        except (ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
            response = {"protocol_version": request.get('protocol_version', 1) if isinstance(locals().get('request'), dict) else 1,
                "request_id": request_id, "ok": False, "error": str(exc)}
        raw = (json.dumps(response, separators=(',', ':'), allow_nan=False) + "\n").encode()
        if response['protocol_version'] == 2 and len(raw) > FRAME_LIMIT:
            raw = (json.dumps({'protocol_version': 2, 'request_id': request_id, 'ok': False,
                'error': 'response budget exceeded; outcome unknown, inspect owned state before retry'}) + '\n').encode()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Immutable acknowledgement evidence survives a disconnected caller.


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = False
    allow_reuse_address = False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, default=Path("/run/explainnet/agent.sock"))
    parser.add_argument("--allow-uid", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/explainnet-agent"))
    parser.add_argument('--stream-receivers', action='store_true')
    parser.add_argument('--allow-lab-test-hooks', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0 or args.allow_uid < 1:
        parser.error("run as root with a non-root allowed UID")
    directory = args.socket.parent
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != 0:
        parser.error("socket directory must be owned by root and not be a symlink")
    caller_gid = pwd.getpwuid(args.allow_uid).pw_gid
    os.chown(directory, 0, caller_gid)
    os.chmod(directory, 0o750)
    if args.socket.exists():
        if not stat.S_ISSOCK(args.socket.stat().st_mode):
            parser.error("refusing to replace a non-socket path")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                probe.connect(str(args.socket))
            parser.error("agent already running")
        except (ConnectionRefusedError, FileNotFoundError):
            args.socket.unlink()
    from explainnet.network_runtime import NetworkManager
    manager = NetworkManager(args.state_dir, stream_receivers=args.stream_receivers)
    manager.allow_lab_test_hooks = args.allow_lab_test_hooks
    try:
        server = Server(str(args.socket), Handler)
    except OSError:
        manager.shutdown()
        raise
    server.network_manager = manager
    server.allowed_uids = {args.allow_uid, 0}
    os.chown(args.socket, 0, caller_gid)
    os.chmod(args.socket, 0o660)

    def stop(_signum, _frame):
        import threading
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        server.network_manager.shutdown()
        args.socket.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
