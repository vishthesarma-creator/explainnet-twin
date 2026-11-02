"""Explicit bounded collection recovery; original recipes and partitions stay reserved."""
from explainnet.dataset_contracts import digest


def recovery_limits(batch, episode):
    amendment = batch.get("recovery_amendment")
    if not amendment or episode.episode_id not in amendment["episodes"]:
        return batch["schedule"]["max_attempts"], episode
    content = {k: v for k, v in amendment.items() if k != "sha256"}
    if (digest(content) != amendment["sha256"] or amendment["version"] not in {"coverage_recovery_v1", "sampling_recovery_v2", "cadence_recovery_v3", "receiver_batch_v4", "linux_storage_v5"}
            or amendment["original_schedule_hash"] != batch["schedule_hash"]
            or amendment["measurement_s"] != 100):
        raise ValueError("incompatible recovery amendment")
    limit = amendment["episodes"][episode.episode_id]["attempt_limit"]
    maximum = {'coverage_recovery_v1': 4, 'sampling_recovery_v2': 6, 'cadence_recovery_v3': 8, 'receiver_batch_v4': 10, 'linux_storage_v5': 10}[amendment['version']]
    if type(limit) is not int or not 2 <= limit <= maximum:
        raise ValueError("unbounded recovery attempt limit")
    return limit, episode.model_copy(update={"scenario": episode.scenario.model_copy(update={"measurement_s": 100})})


def recovery_telemetry(batch, settings):
    amendment = batch.get('recovery_amendment')
    if not amendment or amendment['version'] not in {'cadence_recovery_v3', 'receiver_batch_v4', 'linux_storage_v5'}:
        return settings
    if (digest({k: v for k, v in amendment.items() if k != 'sha256'}) != amendment['sha256']
            or amendment.get('sample_interval_s') != 2 or amendment['original_schedule_hash'] != batch['schedule_hash']):
        raise ValueError('incompatible cadence recovery amendment')
    return settings.model_copy(update={'sample_interval_s': 2.0})
