"""Stdlib native iperf JSON/JSON-stream reader, retaining only complete events."""
import json


def recent_receiver(path, maximum_intervals=30):
    """Bounded native stream view; full owned file remains the raw evidence."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        head = stream.read(65536)
        stream.seek(0)
        first = stream.readline(65536)
        offset = max(len(first), size - 131072)
        stream.seek(offset)
        tail = stream.read(131072)
    if offset > len(first):
        tail = tail.partition(b'\n')[2]
    parsed = native_receiver((first + tail).decode('utf-8'))
    # iperf resets interval time after omission. Keep the MEASURED omitted
    # interval ends, not merely the configured warmup, when trimming history.
    initial = native_receiver(head.decode('utf-8'))
    omitted = [i for i in initial.get('intervals', []) if i.get('sum', {}).get('omitted')]
    parsed['intervals'] = omitted + [i for i in parsed.get('intervals', []) if not i.get('sum', {}).get('omitted')][-maximum_intervals:]
    return parsed


def native_receiver(text):
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or 'event' not in parsed:
            return parsed
    except ValueError:
        pass
    native = {'intervals': []}
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n'):
            continue
        event = json.loads(line)
        name, data = event.get('event'), event.get('data')
        if name in {'start', 'end'}:
            native[name] = data
        elif name == 'interval':
            native['intervals'].append(data)
        elif name == 'error':
            native['error'] = data
    return native
