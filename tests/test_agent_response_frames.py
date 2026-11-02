"""Unix socket transport regression checks; synthetic replies, not packet evidence."""
import json
import socket
import threading
from contextlib import contextmanager

import pytest

from explainnet.agent import AgentClient, AgentUnavailable


@contextmanager
def reply_socket(tmp_path, payload_bytes, *, terminate=True, mismatch=False, invalid=False):
    path = tmp_path / 'agent.sock'
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    def serve():
        with server:
            conn, _ = server.accept()
            with conn:
                request = json.loads(conn.makefile('rb').readline())
                body = {'protocol_version': 1, 'request_id': 'wrong' if mismatch else request['request_id'],
                    'ok': True, 'data': {'native_evidence': 'x' * payload_bytes}}
                frame = b'not-json' if invalid else json.dumps(body).encode()
                frame += b'\n' if terminate else b''
                try:
                    for offset in range(0, len(frame), 16381):
                        conn.sendall(frame[offset:offset + 16381])
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Rejection closes the client before the test producer finishes.
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield AgentClient(path, timeout_s=5, protocol_version=1)
    finally:
        thread.join(10)
        assert not thread.is_alive()


@pytest.mark.parametrize('operation', ['traffic_stop', 'traffic_status'])
def test_long_completed_traffic_frame_keeps_all_evidence(tmp_path, operation):
    length = 2648024
    with reply_socket(tmp_path, length) as client:
        result = client.call(operation, {'schema_version': 1, 'instance_id': 'owned', 'run_id': 'run1'})
    assert result == {'native_evidence': 'x' * length}


def test_unrelated_operations_keep_original_two_mib_limit(tmp_path):
    with reply_socket(tmp_path, 2 * 1024 * 1024) as client, pytest.raises(AgentUnavailable, match='limit 2097152'):
        client.health()


def test_traffic_response_limit_remains_bounded(tmp_path):
    with reply_socket(tmp_path, 8 * 1024 * 1024) as client, pytest.raises(AgentUnavailable, match='limit 8388608'):
        client.call('traffic_status', {'schema_version': 1, 'instance_id': 'owned', 'run_id': 'run1'})


@pytest.mark.parametrize('options,reason', [({'terminate': False}, 'terminator'),
    ({'mismatch': True}, 'mismatch'), ({'invalid': True}, 'Invalid JSON')])
def test_framing_and_request_identity_still_required(tmp_path, options, reason):
    with reply_socket(tmp_path, 100, **options) as client, pytest.raises(AgentUnavailable, match=reason):
        client.health()
