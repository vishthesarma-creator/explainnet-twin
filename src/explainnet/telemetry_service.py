"""Unprivileged bounded sampler, reconstruction, historical views and rule baseline."""

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from explainnet.contracts import ServiceObjective
from explainnet.network_contracts import InstanceRequest
from explainnet.telemetry_contracts import FEATURES, ObserveRequest, TelemetrySettings
from explainnet.telemetry_math import aggregate_windows, receiver_records
from explainnet.telemetry_monitor import evaluate, rules
from explainnet.telemetry_storage import TelemetryRepository


def utc():
    return datetime.now(UTC).isoformat()


def owner_ticks(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class TelemetryService:
    def __init__(self, store, agent, settings=None, objective=None):
        self.store, self.agent = store, agent
        self.settings = settings or TelemetrySettings()
        self.objective = objective or ServiceObjective(max_rtt_ms=100, max_loss_fraction=0.02)
        self.repository = TelemetryRepository(store)
        self.lock = threading.RLock()
        self.collectors = {}

    def reconcile(self):
        for session in self.repository.collectors():
            if session["state"] in {"starting", "running", "stopping"} and owner_ticks(session["owner_pid"]) != session["owner_start_ticks"]:
                recovery = self.repository.recover(session["run_id"])
                session.update(state="interrupted", error="collector process ownership lost; not replayed",
                               recovery=recovery, ended_monotonic_s=session.get("last_monotonic_s", session["started_monotonic_s"]), ended_utc=utc())
                self.repository.save_collector(session)

    def start(self, instance_id, duration_s):
        with self.lock:
            existing = self.collectors.get(instance_id)
            if existing and existing["thread"].is_alive():
                if existing["session"]["duration_s"] != duration_s:
                    raise ValueError("collector already running with different duration")
                return self.status(instance_id)
            network = self.agent.network_inspect(InstanceRequest(instance_id=instance_id))
            if network.get("state") != "running" or not network.get("live_verified"):
                raise ValueError("collector requires a verified live network")
            active = [s for s in self.repository.collectors(instance_id) if s["state"] in {"starting", "running", "stopping"}]
            if active:
                raise ValueError("instance already has a collector; reconcile lost ownership before restart")
            session = {"schema_version": 1, "run_id": "t" + uuid4().hex, "instance_id": instance_id,
                "state": "running", "started_utc": utc(), "started_monotonic_s": time.monotonic(),
                "duration_s": duration_s, "owner_pid": os.getpid(), "owner_start_ticks": owner_ticks(os.getpid()),
                "settings": self.settings.model_dump(), "sample_count": 0, "errors": [], "last_observation_utc": None}
            self.store.insert_record("runs", session["run_id"], {"schema_version": 1, "kind": "telemetry_collection",
                "instance_id": instance_id, "created_utc": session["started_utc"]}, config_hash="telemetry_v1")
            self.repository.save_collector(session)
            stop = threading.Event()
            thread = threading.Thread(target=self._loop, args=(session, stop), name="telemetry-" + instance_id, daemon=False)
            self.collectors[instance_id] = {"session": session, "stop": stop, "thread": thread}
            thread.start()
            return self.status(instance_id)

    def _rebuild(self, session, final=False):
        records = self.repository.samples(session["run_id"])
        windows = aggregate_windows(records, session, self.settings, time.monotonic(), final=final)
        alerts = evaluate(windows, self.settings, self.objective, self.repository.reference(session["instance_id"]))
        self.repository.save_windows(windows, alerts)

    def _loop(self, session, stop):
        seen = set()
        seen_intervals = set()
        next_sample = time.monotonic()
        next_rebuild = next_sample + self.settings.window_s
        deadline = session["started_monotonic_s"] + session["duration_s"]
        try:
            while not stop.is_set() and time.monotonic() < deadline:
                try:
                    observation = self.agent.telemetry_observe(ObserveRequest(instance_id=session["instance_id"],
                        completed_run_ids=sorted(seen)[-256:], since_utc=session["started_utc"], live_receivers=True))
                    observation.update(run_id=session["run_id"], valid=True)
                    self.repository.ingest(observation)
                    arrival = [r for r in receiver_records(observation, session['run_id'])
                               if r['sample_id'] not in seen_intervals]
                    self.repository.ingest_many(arrival)
                    seen_intervals.update(r['sample_id'] for r in arrival)
                    seen.update(r["run_id"] for r in observation["completed_runs"])
                    session.update(last_observation_utc=observation["at_utc"], last_monotonic_s=observation["monotonic_s"],
                                   capabilities=observation["capabilities"], sample_count=session["sample_count"] + 1)
                    # Rebuilding every sample repeatedly serializes the entire growing history.
                    # Publish on window cadence or immediately on native receiver finalization.
                    if time.monotonic() >= next_rebuild or observation["completed_runs"]:
                        self._rebuild(session)
                        next_rebuild = time.monotonic() + self.settings.window_s
                except Exception as exc:  # noqa: BLE001 - persist observation failure without invented values
                    session["errors"].append({"at_utc": utc(), "message": str(exc)})
                    error = {"schema_version": 1, "sample_id": "e" + uuid4().hex, "run_id": session["run_id"],
                        "instance_id": session["instance_id"], "source": "collector_error", "at_utc": utc(),
                        "valid": False, "reason": str(exc), "config_version": None, "units": {}}
                    self.repository.ingest(error)
                self.repository.save_collector(session)
                next_sample += self.settings.sample_interval_s
                next_sample = max(next_sample, time.monotonic())
                stop.wait(max(0, next_sample - time.monotonic()))
        finally:
            session.update(state="stopped", ended_utc=utc(), ended_monotonic_s=time.monotonic())
            try:
                self._rebuild(session, final=True)
            except Exception as exc:  # noqa: BLE001 - retain explicit finalization failure
                session.update(state="failed", error=str(exc))
            self.repository.save_collector(session)

    def stop(self, instance_id):
        with self.lock:
            collector = self.collectors.get(instance_id)
            if collector:
                collector["stop"].set()
        if collector:
            collector["thread"].join(timeout=20)
            if collector["thread"].is_alive():
                raise RuntimeError("collector did not stop within its bounded observation deadline")
        return self.status(instance_id)

    def close(self):
        for instance_id in list(self.collectors):
            self.stop(instance_id)

    def status(self, instance_id):
        with self.lock:
            collector = self.collectors.get(instance_id)
            sessions = self.repository.collectors(instance_id)
            session = dict(collector["session"]) if collector else sessions[0] if sessions else None
            live = bool(collector and collector["thread"].is_alive() and session["state"] == "running")
            age = None
            if session and session.get("last_observation_utc"):
                age = max(0, (datetime.now(UTC) - datetime.fromisoformat(session["last_observation_utc"])).total_seconds())
            remaining = max(0, session['started_monotonic_s'] + session['duration_s'] - time.monotonic()) if live else 0 if session else None
            expiry = (datetime.fromisoformat(session['started_utc']) + timedelta(seconds=session['duration_s'])).isoformat() if session else None
            expired = bool(session and time.monotonic() >= session['started_monotonic_s'] + session['duration_s'])
            live = live and not expired
            return {"instance_id": instance_id, "live": live, "session": session, "observation_age_s": age,
                'expires_utc': expiry, 'remaining_s': remaining, 'expired': expired,
                "status": "collecting" if live and age is not None and age <= self.settings.stale_after_s else
                "starting" if live and age is None else "stale", "observation_utc": session.get("last_observation_utc") if session else None}

    def windows(self, instance_id, limit=50, ready_only=False):
        return {"collector": self.status(instance_id), "windows": self.repository.windows(instance_id, limit, ready_only),
                "feature_allowlist": sorted(FEATURES)}

    def alerts(self, instance_id):
        status = self.status(instance_id)
        with self.store.connection() as db:
            rows = db.execute("SELECT a.payload_json,w.payload_json FROM baseline_alerts a JOIN telemetry_windows w USING(window_id) "
                "WHERE a.instance_id=? AND w.complete=1 ORDER BY w.end_monotonic_s DESC LIMIT 20", (instance_id,)).fetchall()
        history = [json.loads(row[0]) for row in rows]
        latest = history[0] if history else {"status": "insufficient-data", "method": "rule-based monitoring", "violations": []}
        if not status["live"] or status["status"] == "stale":
            latest = latest | {"status": "stale", "freshness_reason": "collector stopped, unavailable or observation too old"}
        elif rows:
            age = max(0, (datetime.now(UTC) - datetime.fromisoformat(latest["observation_utc"])).total_seconds())
            latest = latest | {"observation_age_s": age}
            current_run = (status.get('session') or {}).get('run_id')
            if current_run and json.loads(rows[0][1]).get('run_id') != current_run:
                latest = latest | {'status': 'insufficient-data', 'freshness_reason': 'current collector has no completed rule window'}
            elif age > self.settings.stale_after_s:
                latest = latest | {"status": "stale", "freshness_reason": "last completed window too old"}
        return {"collector": status, "latest": latest, "history": history, "reference": self.repository.reference(instance_id)}

    def set_reference(self, window_id):
        with self.store.connection() as db:
            row = db.execute("SELECT payload_json FROM telemetry_windows WHERE window_id=?", (window_id,)).fetchone()
        if not row:
            raise ValueError("reference window does not exist")
        window = json.loads(row[0])
        if not window["inference_ready"] or rules(window, self.settings, self.objective) or window["features"]["rtt_p95_ms"] is None:
            raise ValueError("reference must be a completed suitable window satisfying service rules")
        reference = {"schema_version": 1, "window_id": window_id, "validated_utc": utc(),
            "rtt_p95_ms": window["features"]["rtt_p95_ms"], "validation": "observed window passed configured service rules"}
        self.repository.save_reference(window["instance_id"], reference)
        return reference
