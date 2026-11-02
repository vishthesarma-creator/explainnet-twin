"""Prospective completion-3 cohort; metadata only, never inference inputs."""
import random

from explainnet.dataset_contracts import CLASSES, Episode, Schedule
from explainnet.scenario_contracts import Scenario
from explainnet.telemetry_contracts import TelemetrySettings

VERSION = 'completion3_v1'
SEED = 20261028
# Independent joint workload/severity families, reserved before observations.
FAMILIES = [
    ('high','udp',1200,8_000_000,False), ('low','tcp',1000,6_000_000,False),
    ('medium','udp',900,7_000_000,False), ('high','tcp',1100,5_000_000,True),
    ('low','udp',700,4_000_000,False), ('medium','tcp',1300,7_500_000,False),
    ('high','udp',1000,6_500_000,False), ('medium','udp',1100,5_500_000,True),
    ('low','tcp',900,7_200_000,False), ('high','udp',1300,6_200_000,False),
    ('medium','udp',800,6_800_000,False), ('high','tcp',700,5_800_000,True)]


def make_completion_schedule(pilot=False):
    episodes = []
    for family, (severity,protocol,packet,demand,reverse) in enumerate(FAMILIES[:1] if pilot else FAMILIES):
        partition = 'pilot' if pilot else 'train' if family<8 else 'validation' if family<10 else 'test'
        for index,kind in enumerate(CLASSES):
            qos = kind=='qos' or kind=='healthy' and family%3==1
            shared = kind=='saturation' or kind=='healthy' and family%3==2
            scenario = Scenario(config_version='dataset_v1',kind=kind,severity=severity,
                measurement_s=45 if pilot else 100,warmup_s=3,
                traffic_profile='qos_competing' if qos else 'shared' if shared else 'moderate',
                high_utilization=kind=='healthy' and shared,critical_bps=2_000_000 if qos else demand,
                bulk_protocol=protocol,packet_size=packet,
                bidirectional=kind in {'loss','latency'} and reverse,
                variation_ms=3 if kind=='latency' and family in {7,11} else 0)
            for repeat in range(1 if pilot else 10):
                ident = f'c3{"p" if pilot else "m"}_{kind}_f{family:02}_r{repeat:02}'
                episodes.append(Episode(episode_id=ident,family_id=f'c3{"p" if pilot else "m"}_{kind}_f{family:02}',
                    partition=partition,scenario=scenario.model_copy(update={'seed':(910_000_000 if pilot else 920_000_000)+family*10000+index*100+repeat}),
                    target_windows=2 if pilot else 6))
    random.Random(SEED).shuffle(episodes)
    return Schedule(schedule_id='c3_qualification_v1' if pilot else 'c3_representative_v1',config_version=VERSION,
        purpose='pilot' if pilot else 'expansion',episodes=episodes,max_attempts=1 if pilot else 2,
        baseline_s=12,recovery_s=12,settling_s=5,
        telemetry=TelemetrySettings(sample_interval_s=2,window_s=10,min_coverage_fraction=.65,
            max_cpu_busy_fraction=.85,max_memory_used_fraction=.85),
        split_policy='Prospectively reserved joint recipe families:8 train/2 validation/2 untouched test per class;10 independently constructed sources per family;6 accepted windows/source. Pilot/debugging separate. Historical examined cohort not pooled.')
