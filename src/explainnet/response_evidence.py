"""Bounded protocol-2 acknowledgements and immutable, integrity-addressed evidence.

Stdlib only: the root agent never imports the application venv.
"""
import base64
import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

FRAME_LIMIT = 256 * 1024
CHUNK_BYTES = 48 * 1024
HYDRATE_LIMIT = 32 * 1024 * 1024
READ_CACHE = OrderedDict()
READ_LOCK = threading.RLock()
READ_OPERATIONS = {'health', 'capabilities', 'inventory', 'network_inspect', 'traffic_status',
    'scenario_inspect', 'twin_status', 'twin_view', 'lab_status', 'telemetry_observe'}


def encoded(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode()


def projection(value, budget=32768):
    """Keep identity/status fields; omitted material is always explicitly marked."""
    if len(encoded(value)) <= budget:
        return value
    if isinstance(value, dict):
        # Bound each branch and the total independently, including native arrays.
        share = max(80, budget // max(1, len(value)))
        result = {k: projection(v, share) for k, v in value.items()}
        if len(encoded(result)) <= budget:
            return result
        keys = ('instance_id', 'run_id', 'twin_id', 'action_id', 'state', 'created_utc', 'ended_utc', 'error')
        return {k: value[k] for k in keys if k in value} | {'details': 'retrieve integrity-referenced evidence'}
    return {'evidence_only': True, 'type': type(value).__name__, 'items': len(value) if isinstance(value, (list, str)) else None}


class EvidenceFiles:
    def __init__(self, directory):
        self.directory = Path(directory)

    def put(self, value, *, read_only=False):
        raw = encoded(value)
        sha = hashlib.sha256(raw).hexdigest()
        if read_only:
            if len(raw) > HYDRATE_LIMIT:
                raise ValueError('read evidence exceeds bounded cache; use existing native artifacts')
            with READ_LOCK:
                READ_CACHE[sha] = raw
                READ_CACHE.move_to_end(sha)
                while sum(map(len, READ_CACHE.values())) > 2 * HYDRATE_LIMIT:
                    READ_CACHE.popitem(last=False)
            return {'schema_version': 1, 'sha256': sha, 'bytes': len(raw), 'encoding': 'json',
                'chunk_bytes': CHUNK_BYTES, 'retention': 'read cache; request status again if evicted'}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (sha + '.json')
        if not path.exists():
            temp = path.with_name(sha + '.' + uuid4().hex + '.tmp')
            with temp.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
        return {'schema_version': 1, 'sha256': sha, 'bytes': len(raw), 'encoding': 'json', 'chunk_bytes': CHUNK_BYTES}

    def page(self, sha256, offset=0):
        if len(sha256) != 64 or any(c not in '0123456789abcdef' for c in sha256):
            raise ValueError('invalid evidence hash')
        if type(offset) is not int or offset < 0:
            raise ValueError('invalid evidence offset')
        path = self.directory / (sha256 + '.json')
        if path.is_symlink():
            raise ValueError('evidence symlink refused')
        with READ_LOCK:
            cached = READ_CACHE.get(sha256)
        size = len(cached) if cached is not None else path.stat().st_size
        if offset > size:
            raise ValueError('offset exceeds evidence size')
        if cached is not None:
            raw = cached[offset:offset + CHUNK_BYTES]
        else:
            with path.open('rb') as stream:
                stream.seek(offset)
                raw = stream.read(CHUNK_BYTES)
        return {'sha256': sha256, 'offset': offset, 'total_bytes': size,
            'next_offset': offset + len(raw), 'base64': base64.b64encode(raw).decode(),
            'complete': offset + len(raw) == size}

    def acknowledgement(self, operation, value):
        ref = self.put(value, read_only=operation in READ_OPERATIONS)
        return {'ack_version': 2, 'operation': operation, 'outcome': 'completed',
            'result': projection(value), 'evidence': ref}
