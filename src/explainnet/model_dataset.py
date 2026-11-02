"""Checksummed measured dataset loader. Sealed test rows are never converted to inputs."""
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass

import numpy as np

from explainnet.dataset_contracts import Schedule, digest
from explainnet.model_contracts import CLASS_ORDER, DATASET_UNITS, FEATURE_ORDER
from explainnet.model_features import feature_array


@dataclass
class Partition:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    episodes: np.ndarray
    windows: list

    def counts(self):
        return {'windows': len(self.y), 'episodes': len(set(self.episodes)), 'families': len(set(self.groups)),
            'classes': dict(Counter(self.y.tolist())), 'episodes_per_class': {c: len(set(self.episodes[self.y == c]))
                for c in CLASS_ORDER}, 'families_per_class': {c: len(set(self.groups[self.y == c])) for c in CLASS_ORDER}}


def load_measured_dataset(directory):
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if (manifest['purpose'] not in {'main','expansion'} or manifest['state'] != 'completed' or not manifest['dataset_ready']
            or manifest['source'] != 'Measured Mininet/OVS/Linux tc/iperf emulation; no synthetic rows'):
        raise ValueError('measured dataset is incomplete or not ready; training refused')
    if (manifest['feature_schema_version'] != 1 or manifest['feature_columns'] != list(FEATURE_ORDER)
            or manifest['units'] != DATASET_UNITS):
        raise ValueError('incompatible feature schema/order/units')
    for name, info in manifest['files'].items():
        if name not in {'features.csv', 'labels.jsonl', 'provenance.jsonl', 'episodes.jsonl',
                         'splits.json', 'schedule.json', 'quality_report.json'}:
            raise ValueError('unsupported dataset artifact')
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('dataset artifact checksum mismatch: ' + name)
    quality = json.loads((directory / 'quality_report.json').read_text())
    if not quality['structural_checks_passed'] or not quality['dataset_ready'] or quality['shortfalls']:
        raise ValueError('required dataset quality gates failed')
    schedule = Schedule.model_validate(json.loads((directory / 'schedule.json').read_text()))
    if digest(schedule.model_dump()) != manifest['schedule_hash']:
        raise ValueError('reserved schedule hash mismatch')
    splits = json.loads((directory / 'splits.json').read_text())
    if set(splits) != {'train', 'validation', 'test'}:
        raise ValueError('reserved partitions missing')
    for kind in ('window_ids', 'episode_ids', 'family_ids'):
        seen = set()
        for partition in splits.values():
            ids = partition[kind]
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                raise ValueError('partition overlap or duplicate ' + kind)
            seen.update(ids)
    episodes = {e.episode_id: e for e in schedule.episodes}
    for p, split in splits.items():
        if set(split['episode_ids']) != {e.episode_id for e in schedule.episodes if e.partition == p}:
            raise ValueError('reserved episode partitions changed')
        if set(split['family_ids']) != {e.family_id for e in schedule.episodes if e.partition == p}:
            raise ValueError('reserved family partitions changed')
    eligible = set(splits['train']['window_ids']) | set(splits['validation']['window_ids'])
    labels, provenance = {}, {}
    for filename, target in [('labels.jsonl', labels), ('provenance.jsonl', provenance)]:
        with (directory / filename).open() as handle:
            for line in handle:
                record = json.loads(line)
                if record['window_id'] in eligible:
                    if record['window_id'] in target:
                        raise ValueError('duplicate eligible metadata')
                    target[record['window_id']] = record
    values = {}
    with (directory / 'features.csv').open(newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ['window_id', *FEATURE_ORDER]:
            raise ValueError('CSV feature order or exclusion failure')
        for row in reader:
            wid = row.pop('window_id')
            if wid not in eligible:
                continue  # Sealed test values are not parsed, imputed, scored or analysed.
            if wid in values:
                raise ValueError('duplicate eligible input')
            values[wid] = {name: None if row[name] == '' else float(row[name]) for name in FEATURE_ORDER}
    if set(values) != eligible or set(labels) != eligible or set(provenance) != eligible:
        raise ValueError('eligible feature/label/provenance mismatch')
    partitions = {}
    for p in ('train', 'validation'):
        ids = splits[p]['window_ids']
        groups, ep, y, windows = [], [], [], []
        for wid in ids:
            label, prov = labels[wid], provenance[wid]
            episode = episodes[label['episode_id']]
            if (episode.partition != p or prov['episode_id'] != episode.episode_id
                    or label['label'] != episode.scenario.kind or label['phase'] != 'steady'
                    or prov['data_quality']['reasons']):
                raise ValueError('eligible metadata not aligned with verified episode')
            groups.append(episode.family_id)
            ep.append(episode.episode_id)
            y.append(label['label'])
            windows.append({'window_id': wid, 'instance_id': 'recorded', 'features': values[wid], 'at_utc': prov['at_utc'],
                'feature_schema_version': 1, 'feature_schema_hash': manifest_hash(), 'complete': True,
                'inference_ready': True, 'data_quality': prov['data_quality'], 'start_monotonic_s': prov['start_monotonic_s'],
                'end_monotonic_s': prov['end_monotonic_s'], 'context':prov.get('context',{})})
        partitions[p] = Partition(feature_array([values[w] for w in ids]), np.asarray(y), np.asarray(groups), np.asarray(ep), windows)
        counts = partitions[p].counts()
        if set(y) != set(CLASS_ORDER) or min(counts['episodes_per_class'].values()) < 2:
            raise ValueError('inadequate independent class coverage')
        if p == 'train' and min(counts['families_per_class'].values()) < 4:
            raise ValueError('insufficient train families for four group-separated folds')
    if len(eligible) + len(splits['test']['window_ids']) != manifest['accepted_windows']:
        raise ValueError('accepted counts disagree with split membership')
    hashes = {'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'split_sha256': manifest['files']['splits.json']['sha256'], 'schedule_sha256': manifest['schedule_hash'],
        'dataset_files': manifest['files'], 'dataset_version': manifest['dataset_version'], 'batch_id': manifest['batch_id']}
    if manifest['dataset_version'] == 'completion3_v1':
        hashes['topology_hash'] = manifest['topology_hash']
    return partitions['train'], partitions['validation'], hashes


def manifest_hash():
    return hashlib.sha256(','.join(FEATURE_ORDER).encode()).hexdigest()
