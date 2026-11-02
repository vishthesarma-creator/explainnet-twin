"""Pure stdlib validation and deterministic paths shared with OS Python agent."""

import hashlib
import ipaddress
import json
import re
from collections import deque
from itertools import combinations, pairwise


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError("invalid fields")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("invalid identifier")
    return value


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"number outside [{low}, {high}]")


def validate_definition(value):
    fields(value, ("schema_version", "config_version", "topology_id", "address_pool", "switches", "hosts", "links", "pairs"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported topology schema")
    identifier(value["topology_id"])
    identifier(value["config_version"])
    pool = ipaddress.ip_network(value["address_pool"])
    if pool.version != 4 or pool.prefixlen != 16 or not pool.is_private:
        raise ValueError("address pool must be a private IPv4 /16")
    switches = value["switches"]
    if not isinstance(switches, list) or not 1 <= len(switches) <= 15 or len(set(switches)) != len(switches):
        raise ValueError("expected 1..15 unique switches")
    if any(not isinstance(s, str) or not re.fullmatch(r"s(?:[1-9]|1[0-5])", s) for s in switches):
        raise ValueError("switch IDs must be s1..s15")
    hosts = value["hosts"]
    if not isinstance(hosts, list) or not 2 <= len(hosts) <= 9:
        raise ValueError("expected 2..9 hosts")
    host_ids, offsets = set(), set()
    for host in hosts:
        fields(host, ("host_id", "switch_id", "address_offset", "role", "access_bps", "access_delay_ms"))
        if not isinstance(host["host_id"], str) or not re.fullmatch(r"h[1-9]", host["host_id"]):
            raise ValueError("host IDs must be h1..h9")
        if host["host_id"] in host_ids or host["switch_id"] not in switches:
            raise ValueError("duplicate host or missing attachment switch")
        if type(host["address_offset"]) is not int or not 1 <= host["address_offset"] <= 254 or host["address_offset"] in offsets:
            raise ValueError("host address offsets must be unique in 1..254")
        identifier(host["role"])
        number(host["access_bps"], 100000, 1000000000)
        number(host["access_delay_ms"], 0, 100)
        host_ids.add(host["host_id"])
        offsets.add(host["address_offset"])
    edges = set()
    for link in value["links"]:
        fields(link, ("source", "target", "forward_bps", "reverse_bps", "forward_delay_ms", "reverse_delay_ms"))
        edge = tuple(sorted((link["source"], link["target"])))
        if link["source"] not in switches or link["target"] not in switches or edge[0] == edge[1] or edge in edges:
            raise ValueError("invalid or duplicate switch link")
        for name in ("forward_bps", "reverse_bps"):
            number(link[name], 100000, 1000000000)
        for name in ("forward_delay_ms", "reverse_delay_ms"):
            number(link[name], 0, 100)
        edges.add(edge)
    if len(edges) > 20:
        raise ValueError("too many links")
    for source in switches:
        for target in switches:
            shortest_path(value, source, target)
    pair_ids, endpoints = set(), set()
    by_host = {h["host_id"]: h for h in hosts}
    for pair in value["pairs"]:
        fields(pair, ("pair_id", "source_host", "target_host", "default_path", "paths"))
        identifier(pair["pair_id"])
        if pair["pair_id"] in pair_ids or pair["source_host"] not in host_ids or pair["target_host"] not in host_ids:
            raise ValueError("invalid pair")
        key = tuple(sorted((pair["source_host"], pair["target_host"])))
        if key[0] == key[1] or key in endpoints:
            raise ValueError("duplicate pair endpoints")
        if not isinstance(pair["paths"], dict) or not pair["paths"] or pair["default_path"] not in pair["paths"]:
            raise ValueError("default path must be allowed")
        for name, path in pair["paths"].items():
            identifier(name)
            if not isinstance(path, list) or not path or len(path) != len(set(path)):
                raise ValueError("path must be simple")
            if path[0] != by_host[pair["source_host"]]["switch_id"] or path[-1] != by_host[pair["target_host"]]["switch_id"]:
                raise ValueError("path endpoints do not match hosts")
            if any(tuple(sorted(edge)) not in edges for edge in pairwise(path)):
                raise ValueError("path contains a missing link")
        pair_ids.add(pair["pair_id"])
        endpoints.add(key)
    return value


def runtime_switch_name(token, switch_id):
    """Keep Linux interface names <=15 bytes, retaining the existing owner token."""
    return f"en{token}s{'0123456789abcdef'[int(switch_id[1:])]}"


def scale_definition(base, size):
    """Deterministic extra switches on the alternate path; original fault links stay."""
    import copy
    if size not in {5, 10, 15}:
        raise ValueError('supported scale sizes are 5, 10 and 15')
    result = copy.deepcopy(base)
    if size == 5:
        return validate_definition(result)
    result['topology_id'] = f'explainnet_{size}'
    result['config_version'] = f'scale_{size}_v1'
    result['switches'] = [f's{i}' for i in range(1,size+1)]
    result['links'] = [l for l in result['links'] if {l['source'],l['target']} != {'s4','s5'}]
    chain = ['s4',*[f's{i}' for i in range(6,size+1)],'s5']
    for a,b in pairwise(chain):
        result['links'].append({'source':a,'target':b,'forward_bps':30000000,'reverse_bps':30000000,
            'forward_delay_ms':1,'reverse_delay_ms':1})
    for pair in result['pairs']:
        pair['paths']['alternative'] = ['s1',*chain]
    return validate_definition(result)


def shortest_path(definition, source, target):
    neighbors = {s: set() for s in definition["switches"]}
    for link in definition["links"]:
        neighbors[link["source"]].add(link["target"])
        neighbors[link["target"]].add(link["source"])
    queue = deque([[source]])
    seen = {source}
    while queue:
        path = queue.popleft()
        if path[-1] == target:
            return path
        for neighbor in sorted(neighbors[path[-1]]):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append([*path, neighbor])
    raise ValueError("topology is disconnected")


def host_routes(definition, selected):
    hosts = {h["host_id"]: h for h in definition["hosts"]}
    configured = {tuple(sorted((p["source_host"], p["target_host"]))): p for p in definition["pairs"]}
    result = []
    for index, (a, b) in enumerate(combinations(sorted(hosts), 2), start=1):
        pair = configured.get((a, b))
        if pair:
            chosen = selected.get(pair["pair_id"], pair["default_path"])
            path = pair["paths"][chosen]
            if a != pair["source_host"]:
                path = list(reversed(path))
        else:
            path = shortest_path(definition, hosts[a]["switch_id"], hosts[b]["switch_id"])
        result.append({"source_host": a, "target_host": b, "switches": path, "cookie_index": index,
                       "pair_id": pair["pair_id"] if pair else None})
    return result


def definition_hash(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_profile(profile, definition):
    fields(profile, ("schema_version", "config_version", "profile_id", "source_host", "target_host", "protocol", "offered_bps", "duration_s", "packet_size"), ("warmup_s", "stream_receiver"))
    if type(profile.get('stream_receiver', False)) is not bool:
        raise ValueError('invalid receiver streaming flag')
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("unsupported traffic schema")
    identifier(profile["config_version"])
    identifier(profile["profile_id"])
    hosts = {h["host_id"] for h in definition["hosts"]}
    if profile["source_host"] not in hosts or profile["target_host"] not in hosts or profile["source_host"] == profile["target_host"]:
        raise ValueError("invalid traffic endpoints")
    if profile["protocol"] not in ("tcp", "udp"):
        raise ValueError("unsupported traffic protocol")
    number(profile["offered_bps"], 1000, 100000000)
    if type(profile["duration_s"]) is not int or not 1 <= profile["duration_s"] <= (2400 if profile["config_version"] == "workflow_observation_v1" else 900 if profile["config_version"] == "recovery_observation_v1" else 100):
        raise ValueError("traffic duration exceeds bounded configuration limit")
    if type(profile.get("warmup_s", 0)) is not int or not 0 <= profile.get("warmup_s", 0) <= 5:
        raise ValueError("traffic warmup must be 0..5 seconds")
    if profile["packet_size"] is not None and (profile["protocol"] != "udp" or type(profile["packet_size"]) is not int or not 64 <= profile["packet_size"] <= 1400):
        raise ValueError("UDP packet size must be 64..1400 bytes")
    return profile
