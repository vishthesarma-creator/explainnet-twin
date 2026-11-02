"""Sequential durable experiment runner using existing jobs and agent ownership."""

import fcntl
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

from explainnet.dataset_contracts import Schedule, digest
from explainnet.dataset_export import atomic_json, export_dataset, phase_for_window
from explainnet.dataset_recovery import recovery_limits, recovery_telemetry
from explainnet.dataset_repository import DatasetRepository
from explainnet.network_contracts import InstanceRequest, TrafficRunRequest
from explainnet.storage import utc_now
from explainnet.telemetry_service import owner_ticks


class CollectionCanceled(RuntimeError):
    pass


def receiver_summary(traffic):
    item = next(p for p in traffic["profiles"] if p["parameters"]["profile_id"] == "critical")
    end = (item.get("server_json") or {}).get("end", {})
    result = end.get("sum_received", end.get("sum"))
    if not result or "bits_per_second" not in result or "lost_percent" not in result:
        raise ValueError("critical UDP receiver summary unavailable")
    return {"goodput_bps": result["bits_per_second"], "loss_fraction": result["lost_percent"] / 100,
            "offered_bps": item["parameters"]["offered_bps"]}


def verify_healthy(traffic):
    measured = receiver_summary(traffic)
    if measured["loss_fraction"] > 0.02 or measured["goodput_bps"] < 0.8 * measured["offered_bps"]:
        raise ValueError("healthy control failed measured receiver service: " + json.dumps(measured))
    return measured


class DatasetService:
    def __init__(self, store, agent, submit, telemetry, definition=None, config_hash="", artifact_dir=None):
        self.store, self.agent, self.submit, self.telemetry = store, agent, submit, telemetry
        self.definition, self.config_hash, self.artifact_dir = definition, config_hash, artifact_dir
        self.repository = DatasetRepository(store)
        self.lock = threading.RLock()
        self.thread, self.cancel_event, self.active_id = None, threading.Event(), None
        self.file_lock = None

    def reconcile(self):
        for batch in self.repository.batches():
            if batch["state"] == "running" and owner_ticks(batch["owner_pid"]) != batch["owner_start_ticks"]:
                batch.update(state="interrupted", error="runner ownership lost; explicit resume required")
                self.repository.save_batch(batch)
                for attempt in self.repository.attempts(batch["batch_id"]):
                    if attempt["state"] == "running":
                        attempt.update(state="interrupted", error="runner interrupted; owned resource reconciliation required")
                        self.repository.save_attempt(attempt)

    def plan(self, schedule):
        schedule = Schedule.model_validate(schedule)
        if self.definition is None:
            raise ValueError("dataset collection requires a configured topology")
        schedule_hash = digest(schedule.model_dump())
        for batch in self.repository.batches():
            if batch["schedule"]["schedule_id"] == schedule.schedule_id:
                if batch["schedule_hash"] != schedule_hash or batch["config_hash"] != self.config_hash:
                    raise ValueError("existing schedule ID has incompatible configuration; use a new version/ID")
                return batch
        batch = {"schema_version": 1, "batch_id": "d" + uuid4().hex, "state": "planned",
            "created_utc": utc_now(), "schedule": schedule.model_dump(), "schedule_hash": schedule_hash,
            "definition": self.definition.model_dump(), "config_hash": self.config_hash,
            "owner_pid": os.getpid(), "owner_start_ticks": owner_ticks(os.getpid()),
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir else None, "errors": [],
            "environment": {"agent_capabilities": self.agent.capabilities()}}
        self.repository.save_batch(batch)
        return batch

    def status(self, batch_id, details=False):
        batch = self.repository.batch(batch_id)
        if not batch:
            raise ValueError("unknown dataset batch")
        if (batch['state'] == 'running' and self.active_id == batch_id and self.thread
                and not self.thread.is_alive()):
            batch.update(state='failed', error='runner thread exited without a terminal checkpoint; explicit resume required')
            self.repository.save_batch(batch)
        attempts = self.repository.attempts(batch_id) if details else self.repository.attempt_summaries(batch_id)
        return {"batch": batch, "attempts": attempts, "accepted_windows": len(self.repository.members(batch_id)),
                "completed_episodes": len({a["episode_id"] for a in attempts if a["state"] == "completed"}),
                "live": bool(self.active_id == batch_id and self.thread and self.thread.is_alive()),
                "runner_pid": batch["owner_pid"], "manifest_path": batch.get("manifest_path")}

    def _verify_completed(self, batch):
        for attempt in self.repository.iter_attempts(batch["batch_id"]):
            if attempt["state"] != "completed":
                continue
            path = Path(attempt["raw_path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != attempt["raw_sha256"]:
                raise ValueError("completed episode raw evidence changed")
            episode = next(e for e in batch["schedule"]["episodes"] if e["episode_id"] == attempt["episode_id"])
            if len(attempt["accepted_window_ids"]) != episode["target_windows"] or not attempt["restoration_verified"]:
                raise ValueError("completed episode has invalid checkpoint")
        result = export_dataset(self.store, batch["batch_id"])
        if not result["quality"]["structural_checks_passed"]:
            raise ValueError("completed dataset evidence audit failed")

    def start(self, batch_id, resume=False):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.active_id == batch_id:
                    return self.status(batch_id)
                raise ValueError("another dataset batch is running")
            batch = self.repository.batch(batch_id)
            if not batch:
                raise ValueError("unknown dataset batch")
            if batch["state"] == "completed":
                self._verify_completed(batch)
                return self.status(batch_id)
            if batch["config_hash"] != self.config_hash or batch["definition"] != self.definition.model_dump():
                raise ValueError("batch configuration changed; incompatible resume refused")
            if batch['schedule']['config_version']=='completion3_v1' and batch['schedule']['purpose']=='expansion':
                pilots = [p for p in self.repository.batches() if p['schedule']['schedule_id']=='c3_qualification_v1' and p['state']=='completed']
                if not pilots:
                    raise ValueError('completion3 expansion requires its completed measured five-class pilot')
                for pilot in pilots:
                    audit = export_dataset(self.store, pilot['batch_id'])['quality']
                    if audit['structural_checks_passed'] and not audit['shortfalls'] and audit['accepted_windows']==10:
                        break
                else:
                    raise ValueError('completion3 pilot quality/coverage/restoration gates failed')
            if batch["state"] != "planned" and not resume:
                raise ValueError("interrupted/failed/canceled batches require explicit resume")
            owned = {a["instance_id"] for a in self.repository.attempts(batch_id)}
            if any(r["state"] == "running" and r["instance_id"] not in owned
                   for r in self.agent.inventory().get("instances", [])):
                raise ValueError("another live network exists; sequential collection requires an idle laboratory")
            if any(c["state"] in {"starting", "running", "stopping"} and c["instance_id"] not in owned
                   for c in self.telemetry.repository.collectors()):
                raise ValueError("another collector is active")
            self.file_lock = Path(f"/var/tmp/explainnet-experiment-{os.getuid()}.lock").open("a+")  # noqa: SIM115 - held for runner lifetime
            try:
                fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._verify_completed(batch)
                batch.update(state="running", owner_pid=os.getpid(), owner_start_ticks=owner_ticks(os.getpid()),
                             started_utc=utc_now(), error=None)
                self.repository.save_batch(batch)
            except BaseException:
                self.file_lock.close()
                self.file_lock = None
                raise
            self.cancel_event.clear()
            self.active_id = batch_id
            self.thread = threading.Thread(target=self._loop, args=(batch,), name="dataset-" + batch_id, daemon=False)
            self.thread.start()
            return self.status(batch_id)

    def cancel(self, batch_id):
        if self.active_id == batch_id:
            self.cancel_event.set()
        else:
            batch = self.repository.batch(batch_id)
            if not batch:
                raise ValueError("unknown batch")
            if batch["state"] == "planned":
                batch["state"] = "canceled"
                self.repository.save_batch(batch)
        return self.status(batch_id)

    def _job(self, operation, payload, ignore_cancel=False, timeout_s=105):
        if self.cancel_event.is_set() and not ignore_cancel:
            raise CollectionCanceled("collection canceled")
        job_id = self.submit(operation, "dataset-runner", payload)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            job = self.store.get_job(job_id)
            if job["state"] in {"succeeded", "failed", "interrupted", "canceled"}:
                if job["state"] != "succeeded":
                    raise RuntimeError(f"{operation} job {job_id}: {job['error'] or job['state']}")
                return job["result"]
            # Finish an in-flight operation before exact-owner cleanup; cancellation does not race mutation.
            time.sleep(0.1)
        self.store.cancel_job(job_id)
        raise TimeoutError(f"bounded {operation} job deadline exceeded: {job_id}")

    def _checkpoint(self, batch, attempt=None):
        self.repository.save_batch(batch)
        if attempt:
            self.repository.save_attempt(attempt)
        directory = self.store.path.parent / "datasets" / batch["batch_id"]
        atomic_json(directory / "checkpoint.json", self.status(batch["batch_id"]))

    def _wait_traffic(self, instance_id, run_id, maximum_s):
        deadline = time.monotonic() + maximum_s + 15
        while time.monotonic() < deadline:
            if self.cancel_event.is_set():
                raise CollectionCanceled("collection canceled during traffic")
            result = self.agent.traffic_status(TrafficRunRequest(instance_id=instance_id, run_id=run_id))
            if result["state"] != "running":
                self.store.update_run(run_id, result)
                if result["state"] != "succeeded":
                    raise ValueError("traffic measurement failed: " + result["state"])
                return result
            self.cancel_event.wait(0.5)
        raise TimeoutError("traffic exceeded its declared bounded duration")

    def _phase(self, batch, attempt, scenario, role):
        instance_id = attempt["instance_id"]
        batch["phase"] = role
        self._checkpoint(batch, attempt)
        started = self._job("scenario_start", {"instance_id": instance_id, "scenario": scenario.model_dump()})
        attempt[role + "_start_receipt"] = started
        journal = started["laboratory_journal"]
        if journal["state"] != "active" or not journal["activated_utc"]:
            raise ValueError("scenario was not successfully applied")
        if journal["configuration"] != scenario.model_dump():
            raise ValueError("actual application differs from declared scenario")
        self._checkpoint(batch, attempt)
        traffic = self._wait_traffic(instance_id, journal["owned_runs"][0], scenario.measurement_s + scenario.warmup_s)
        attempt[role + "_traffic"] = traffic
        # Allow finalized native receiver intervals to reach the existing collector.
        allowance = 35 if batch.get('recovery_amendment', {}).get('version') in {'cadence_recovery_v3', 'receiver_batch_v4', 'linux_storage_v5'} else 12
        deadline = time.monotonic() + allowance
        while time.monotonic() < deadline:
            records = self.telemetry.repository.samples(attempt["collector_run_id"])
            if any(r.get("traffic_run_id") == traffic["run_id"] for r in records):
                break
            if self.cancel_event.wait(0.3):
                raise CollectionCanceled("collection canceled awaiting receiver finalization")
        else:
            raise ValueError("receiver intervals did not reach the collector")
        reset = self._job("scenario_reset", {"instance_id": instance_id}, ignore_cancel=True)
        attempt[role + "_reset_receipt"] = reset
        if reset["laboratory_journal"]["state"] != "stopped" or reset["laboratory_journal"]["restore_errors"]:
            raise ValueError("scenario restoration unverified")
        self._checkpoint(batch, attempt)
        return traffic

    def _cleanup(self, attempt):
        errors = []
        instance_id = attempt["instance_id"]
        # Exact per-attempt names are persisted before creation; no global cleanup.
        for operation in ("scenario_reset", "collector_stop", "network_stop"):
            try:
                result = self._job(operation, {"instance_id": instance_id}, ignore_cancel=True)
                attempt["cleanup_" + operation] = result
            except Exception as exc:  # noqa: BLE001 - preserve explicit restoration/ownership failures
                if operation == "scenario_reset":
                    try:
                        observed = self.agent.network_inspect(InstanceRequest(instance_id=instance_id))
                        if observed["state"] == "stopped" or (observed["state"] == "failed" and not observed.get("live_verified")):
                            attempt.setdefault("cleanup_warnings", []).append("lost scenario owner; owned network teardown required")
                            continue
                    except Exception as inspect_error:  # noqa: BLE001 - retain failed ownership inspection
                        attempt.setdefault("cleanup_warnings", []).append(str(inspect_error))
                errors.append(f"{operation}: {exc}")
        attempt["cleanup_errors"] = errors
        return not errors

    def _recover_attempts(self, batch):
        for attempt in self.repository.iter_attempts(batch["batch_id"]):
            if attempt["state"] in {"running", "interrupted"} or (attempt["state"] != "completed" and not attempt.get("cleanup_verified")):
                attempt["cleanup_verified"] = self._cleanup(attempt)
                attempt["state"] = "interrupted"
                self.repository.save_attempt(attempt)
                if not attempt["cleanup_verified"]:
                    raise ValueError("interrupted episode cleanup failed; manual ownership review required")

    def _episode(self, batch, episode):
        schedule = Schedule.model_validate(batch["schedule"])
        old = self.repository.attempts(batch["batch_id"], episode.episode_id)
        attempt = {"attempt_id": "a" + uuid4().hex, "batch_id": batch["batch_id"], "episode_id": episode.episode_id,
            "partition": episode.partition, "family_id": episode.family_id, "state": "running", "number": len(old) + 1,
            "started_utc": utc_now(), "instance_id": "dataset_" + uuid4().hex[:12], "rejected_windows": []}
        self.repository.save_attempt(attempt)
        batch["current_episode"] = episode.episode_id
        started = time.monotonic()
        try:
            self._job("network_start", {"instance_id": attempt["instance_id"], "definition": batch["definition"]})
            if not self.cancel_event.is_set():
                duration = 300 if batch.get('recovery_amendment', {}).get('version') in {'cadence_recovery_v3', 'receiver_batch_v4', 'linux_storage_v5'} else 240
                collection = self._job("collector_start", {"instance_id": attempt["instance_id"], "duration_s": duration})
                attempt["collector_run_id"] = collection["session"]["run_id"]
                self._checkpoint(batch, attempt)
            else:
                raise CollectionCanceled("collection canceled at startup")
            healthy = episode.scenario.model_copy(update={"kind": "healthy", "bidirectional": False,
                "variation_ms": 0, "high_utilization": episode.scenario.traffic_profile == "shared"})
            baseline = self._phase(batch, attempt, healthy.model_copy(update={"measurement_s": schedule.baseline_s}), "baseline")
            attempt["baseline_service"] = verify_healthy(baseline)
            main = self._phase(batch, attempt, episode.scenario, "main")
            attempt["application_verified"] = True
            if episode.scenario.kind == "healthy":
                attempt["healthy_service"] = verify_healthy(main)
            restored = self._phase(batch, attempt, healthy.model_copy(update={"measurement_s": schedule.recovery_s}), "recovery")
            attempt["recovery_service"] = verify_healthy(restored)
            attempt["restoration_verified"] = True
            self._job("collector_stop", {"instance_id": attempt["instance_id"]}, ignore_cancel=True)
            candidates = sorted((w for w in self.telemetry.repository.windows(attempt["instance_id"], 200)
                                 if w["run_id"] == attempt["collector_run_id"]), key=lambda w: w["start_monotonic_s"])
            accepted = []
            for window in candidates:
                phase = phase_for_window(window, attempt["main_reset_receipt"], main, schedule.settling_s)
                if phase == "steady" and len(accepted) < episode.target_windows:
                    accepted.append(window)
                else:
                    attempt["rejected_windows"].append({"window_id": window["window_id"],
                        "reasons": [phase if phase != "steady" else "surplus_steady_window", *window["data_quality"]["reasons"]]})
            if len(accepted) != episode.target_windows:
                raise ValueError(f"steady window shortfall: {len(accepted)}/{episode.target_windows}")
            if not self._cleanup(attempt):
                raise ValueError("episode cleanup failed")
            attempt["cleanup_verified"] = True
            raw_path = self.telemetry.repository.directory / (attempt["collector_run_id"] + ".jsonl")
            attempt.update(raw_path=str(raw_path), raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                ended_utc=utc_now(), elapsed_s=time.monotonic() - started)
            self.repository.accept(attempt, episode, accepted)
        except Exception as exc:
            attempt.update(state="canceled" if isinstance(exc, CollectionCanceled) else "failed", error=str(exc),
                           ended_utc=utc_now(), elapsed_s=time.monotonic() - started)
            attempt["cleanup_verified"] = self._cleanup(attempt)
            if attempt.get("collector_run_id") and not attempt["rejected_windows"]:
                for window in self.telemetry.repository.windows(attempt["instance_id"], 200):
                    if window["run_id"] == attempt["collector_run_id"]:
                        attempt["rejected_windows"].append({"window_id": window["window_id"],
                            "reasons": ["failed_or_canceled_episode", *window["data_quality"]["reasons"]]})
            self.repository.save_attempt(attempt)
            raise
        self._checkpoint(batch)

    def _loop(self, batch):
        schedule = Schedule.model_validate(batch["schedule"])
        try:
            # Temporarily use the schedule's declared sampler, retaining application defaults afterwards.
            previous_settings = self.telemetry.settings
            self.telemetry.settings = recovery_telemetry(batch, schedule.telemetry)
            exported = export_dataset(self.store, batch["batch_id"])
            batch["manifest_path"] = exported["manifest_path"]
            self._recover_attempts(batch)
            for episode in schedule.episodes:
                history = self.repository.attempts(batch["batch_id"], episode.episode_id)
                if any(a["state"] == "completed" for a in history):
                    continue
                if self.cancel_event.is_set():
                    raise CollectionCanceled("collection canceled between episodes")
                attempt_limit, effective_episode = recovery_limits(batch, episode)
                while len(history) < attempt_limit:
                    try:
                        self._episode(batch, effective_episode)
                        break
                    except CollectionCanceled:
                        raise
                    except Exception as exc:
                        history = self.repository.attempts(batch["batch_id"], episode.episode_id)
                        batch["errors"].append({"episode_id": episode.episode_id, "at_utc": utc_now(), "error": str(exc)})
                        self._checkpoint(batch)
                        if not history[-1].get("cleanup_verified") or len(history) >= attempt_limit:
                            raise
                else:
                    raise ValueError("episode exhausted its declared attempt budget")
                exported = export_dataset(self.store, batch["batch_id"])
                batch["manifest_path"] = exported["manifest_path"]
                self._checkpoint(batch)
            batch.update(state="completed", phase="finalized", ended_utc=utc_now())
        except Exception as exc:  # noqa: BLE001 - persist cancellation/failure, never claim ready
            batch.update(state="canceled" if isinstance(exc, CollectionCanceled) else "failed", error=str(exc), ended_utc=utc_now())
            atomic_json(self.store.path.parent / 'datasets' / batch['batch_id'] / 'runner_failure.json',
                {'at_utc': utc_now(), 'error': str(exc), 'phase': batch.get('phase'),
                 'current_episode': batch.get('current_episode'), 'owner_pid': os.getpid()})
        finally:
            self.telemetry.settings = previous_settings
            try:
                self.repository.save_batch(batch)
                result = export_dataset(self.store, batch["batch_id"])
                batch["manifest_path"] = result["manifest_path"]
                if batch["state"] == "completed" and not result["quality"]["structural_checks_passed"]:
                    batch.update(state="failed", error="final structural audit failed")
            except Exception as exc:  # noqa: BLE001 - preserve final export failure
                batch.update(state="failed", error="export failed: " + str(exc))
            try:
                self._checkpoint(batch)
            finally:
                fcntl.flock(self.file_lock, fcntl.LOCK_UN)
                self.file_lock.close()
                self.file_lock = None

    def close(self, timeout_s=100):
        self.cancel_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout_s)
            if self.thread.is_alive():
                raise RuntimeError("dataset runner did not finish owned cleanup before shutdown")
