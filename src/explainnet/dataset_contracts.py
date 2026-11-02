"""Predeclared episode/family splits; no observations or fitted preprocessing."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from explainnet.contracts import Identifier, Record
from explainnet.scenario_contracts import Scenario
from explainnet.telemetry_contracts import TelemetrySettings

CLASSES = ("healthy", "saturation", "loss", "latency", "qos")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Episode(Record):
    episode_id: Identifier
    family_id: Identifier
    partition: Literal["train", "validation", "test", "pilot"]
    scenario: Scenario
    target_windows: int = Field(ge=1, le=10)


class Schedule(Record):
    schedule_id: Identifier
    config_version: Literal["compact_v1", "pilot_v1", "expansion_v1", "completion3_v1"]
    purpose: Literal["pilot", "main", "expansion"]
    max_attempts: int = Field(default=2, ge=1, le=2)
    settling_s: int = Field(default=5, ge=3, le=10)
    baseline_s: int = Field(default=8, ge=4, le=20)
    recovery_s: int = Field(default=8, ge=4, le=20)
    telemetry: TelemetrySettings = TelemetrySettings()
    episodes: list[Episode] = Field(min_length=5, max_length=1000)
    split_policy: str

    @model_validator(mode="after")
    def grouped(self):
        if self.telemetry.window_s != 10:
            raise ValueError("initial dataset requires ten-second windows")
        identities, families, recipes = set(), {}, {}
        coverage = {p: set() for p in ("pilot",) if self.purpose == "pilot"}
        if self.purpose != "pilot":
            coverage = {p: set() for p in ("train", "validation", "test")}
        for episode in self.episodes:
            if episode.episode_id in identities:
                raise ValueError("duplicate episode ID")
            identities.add(episode.episode_id)
            if episode.partition not in coverage:
                raise ValueError("pilot and sealed main partitions must be separate")
            coverage[episode.partition].add(episode.scenario.kind)
            old = families.setdefault(episode.family_id, episode.partition)
            if old != episode.partition:
                raise ValueError("family crosses partitions")
            # Same recipe, apart from seed/duration, is a close repetition even if renamed.
            recipe = episode.scenario.model_dump(exclude={"seed", "measurement_s"})
            signature = digest(recipe)
            old = recipes.setdefault(signature, (episode.family_id, episode.partition))
            if old != (episode.family_id, episode.partition):
                raise ValueError("related recipe repetitions must use one family")
            if episode.scenario.measurement_s < episode.target_windows * 10 + self.settling_s + 8:
                raise ValueError("insufficient declared measurement time for target windows")
        if any(kinds != set(CLASSES) for kinds in coverage.values()):
            raise ValueError("each partition must cover all five classes")
        return self


class DatasetRunRequest(Record):
    schedule: Schedule


class BatchRequest(Record):
    batch_id: Identifier


def make_schedule(purpose="main"):
    pilot = purpose == "pilot"
    expansion = purpose == "expansion"
    repetitions = 20 if expansion else 1 if pilot else 2
    episodes = []
    for family in range(1 if pilot else 6):
        partition = "pilot" if pilot else "train" if family < 4 else "validation" if family == 4 else "test"
        for kind in CLASSES:
            qos = kind == "qos" or (kind == "healthy" and family in {1, 4})
            shared = kind == "saturation" or (kind == "healthy" and family in {2, 5})
            severity = "high" if pilot else ("low", "medium", "high", "high", "medium", "high")[family]
            scenario = Scenario(config_version="dataset_v1", kind=kind, severity=severity,
                measurement_s=38 if pilot else 85, warmup_s=2,
                traffic_profile="qos_competing" if qos else "shared" if shared else "moderate",
                high_utilization=kind == "healthy" and shared,
                critical_bps=2_000_000 if qos else (8_000_000 if pilot else (6, 8, 8, 7, 5, 6)[family] * 1_000_000),
                bulk_protocol="udp" if pilot or family % 2 == 0 else "tcp",
                packet_size=1200 if pilot else (1200, 1000, 1200, 1000, 600, 1400)[family],
                bidirectional=kind in {"loss", "latency"} and family in {3, 5},
                variation_ms=3 if kind == "latency" and family == 5 else 0)
            for repetition in range(repetitions):
                scenario = scenario.model_copy(update={"seed": 610000 + family * 1000 + CLASSES.index(kind) * 100 + repetition})
                episodes.append(Episode(episode_id=f"{purpose}_{kind}_f{family}_r{repetition}",
                    family_id=f"{purpose}_{kind}_f{family}", partition=partition, scenario=scenario,
                    target_windows=2 if pilot else 6))
    return Schedule(schedule_id=f"{purpose}_initial_v1",
        config_version="pilot_v1" if pilot else "expansion_v1" if expansion else "compact_v1",
        purpose=purpose, episodes=episodes,
        split_policy="Families reserved before collection: 4 train, 1 validation, 1 test per class; 8/2/2 episodes per class (66.7/16.7/16.7%). Pilot is disjoint. Evaluation reserves distinct demand/packet size/direction combinations.")
