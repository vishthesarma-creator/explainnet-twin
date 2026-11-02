# ExplainNet Twin

ExplainNet Twin is a Computer Networks course project for measuring an emulated network, diagnosing faults, explaining predictions and comparing repairs in an isolated digital twin before optional assisted application to the original laboratory.

It uses real Mininet/OVS/Linux traffic-control dataplanes and iperf3/probe/counter observations. Dashboard values are measurements, not simulated live counters. Production-network automatic remediation is outside scope. Automatic repair is disabled by default.

## Architecture and interface

```text
Four-page Streamlit UI → unprivileged FastAPI → SQLite and local model/evidence store
                                      ↓ UID-bound typed Unix-socket RPC
                            separate privileged OS-Python Mininet agent
                                      ↓
                         isolated original and twin dataplanes
```

| Page | Purpose |
|---|---|
| Live Network | Owned topology/routes, configured capacity separately from measured utilization, receiver delivery/loss/jitter, RTT/history gaps, collector/workload expiry and deliberate guided controls |
| Diagnosis | Relevant network/session incident, rule findings, actual Isolation Forest/Random Forest results, calibrated probabilities/support and matching per-event SHAP |
| Twin & Recovery | Observation/snapshot/reconstruction, measured no-change fidelity, candidate comparisons/costs/protected traffic, exact refusal reasons, optional assisted application, original verification, rollback and Undo |
| Results | Historical measured results, prospective dataset status, software checks and locally available approved artifacts |

Shared manual and10-second refresh controls, backend/profile identity, readiness, observation age and mode remain visible. Reads/navigation do not start experiments or enable exceptions. Source/ground-truth records stay separate from inference features. RTT/jitter use milliseconds, rates bits/second, loss/utilization fractions, stored timestamps UTC and elapsed durations monotonic clocks; missing values remain null.

## Verified scope and limitations

The latest recorded integration evidence is dated28 October2026, not a claim about the current state of any running network. This public upload does not run new experiments or retrain.

- Four fault classes are implemented: shared-link saturation, netem packet loss, latency/variation and the declared HTB QoS restriction; healthy is a separate dataset label.
- Historical local training uses Isolation Forest, a calibrated Random Forest and training-background per-event SHAP. SHAP explains raw RF output and is neither calibrated confidence nor proof of causality.
- A bounded trained five-switch UDP latency rehearsal passed matching diagnosis/SHAP, four no-change fidelity controls,12 trials/two distinct changing reroutes, assisted original verification and explicit Undo. Two settled original windows measured meanRTT about4.29/4.30ms, approximately8Mbps critical delivery and zero measured settled UDP loss. Total source run was about683s including Undo/cleanup; that is not inference or intrinsic decision time.
- Healthy operation was refused without unnecessary original repair. A fresh loss comparison refused because ping-loss fidelity residual0.031746 exceeded tolerance0.03; high model confidence did not override it. Saturation/QoS and all-fault recovery remain unqualified at their measurement/fidelity gates.
- Historical macro-F1 was1.000 on only60 windows/ten episodes with one held-out family/class. It does not establish representative generalization or larger-topology transfer.
- The later representative cohort stopped at402/3600 accepted windows (67/600 episodes). Both permitted attempts for one episode produced only1/6 suitable steady windows. New confirmatory model freeze/holdout, independent no-twin/no-XAI comparisons and repeated5/10/15-switch benchmarks remain pending. The integrated decision-time target below10s is unmet.

**Full review acceptance remains blocked.** See [final acceptance](docs/FINAL_ACCEPTANCE.md), [artifact generation](docs/PUBLIC_ARTIFACTS.md) and [publication scope](docs/PUBLICATION.md). Historical guides are retained with anonymized paths; their older statuses/layouts do not supersede this summary. Private raw evidence and model/data bundles are not bundled as public proof.

## Prerequisites

The tested local environment was Linux under WSL2 with Python3.14, Mininet2.3, OVS3.7, iperf3 and iproute2/tc. Python>=3.14 is declared in `pyproject.toml`; exact application pins are in `requirements.txt`. Clean-machine/cross-machine installation has not been validated. Windows users run application/network commands inside a suitable WSL Ubuntu environment.

Required OS tools: Mininet, Open vSwitch with its service available, iperf3, iproute2/tc and ping; tcpdump is useful for deliberate debugging. Install compatible packages using your Linux distribution's documented package manager. The privileged agent uses **OS `/usr/bin/python3` with Mininet installed**, while API/UI/ML use an ordinary-user virtual environment. Never run Streamlit as root or attach a physical/LAN interface to the emulated dataplane.

## Install and configure a fresh clone

```bash
git clone https://github.com/vishthesarma-creator/explainnet-twin.git
cd explainnet-twin
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip check
```

Create a private local configuration using the safe example. This writes no existing database and starts no service:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
import yaml
settings = yaml.safe_load(Path('config/example.yaml').read_text())
base = Path.home() / '.local/share/explainnet-public'
settings.update(data_dir=str(base / 'data'), runtime_dir=str(base / 'run'),
                agent_socket='/run/explainnet-public/agent.sock', port=8765,
                topology_file=str(Path('config/topology.yaml').resolve()),
                traffic_profiles_file=str(Path('config/traffic.yaml').resolve()))
target = Path('config/local.json')
if target.exists():
    raise SystemExit('Existing local configuration preserved; edit it intentionally.')
target.write_text(json.dumps(settings, indent=2) + '\n')
PY
.venv/bin/explainnet --config config/local.json init
```

`init` applies additive SQLite migrations; it does not delete an existing store. Keep example policies conservative. Local configuration, databases, models, job journals and runtime receipts are ignored by Git. No credentials, paid API or cloud inference service is required.

## Startup and shutdown

For a fresh clone, use the configurable launcher instead of the old machine-specific profiles in `scripts/app.py`:

```bash
.venv/bin/python scripts/manage_app.py --config config/local.json --dashboard-port 8501 check
.venv/bin/python scripts/manage_app.py --config config/local.json --dashboard-port 8501 start
.venv/bin/python scripts/manage_app.py --config config/local.json --dashboard-port 8501 status
```

Open http://127.0.0.1:8501; the example API is http://127.0.0.1:8765 and its API documentation is `/docs`. Both services must use the same configuration, API URL and evidence store. The launcher records owned process identity and does not create networks, collect data, train or enable repair.

Live operations additionally require the separate root agent. In a second Linux terminal, from the repository root:

```bash
sudo env PYTHONPATH=src /usr/bin/python3 -m explainnet.agent_server \
  --allow-uid "$(id -u)" \
  --socket /run/explainnet-public/agent.sock \
  --state-dir /var/lib/explainnet-public \
  --stream-receivers
```

Keep this foreground agent terminal open while the laboratory is active. Ordinary managed API/UI services do not need their initiating terminal. Starting the agent creates no network. Never reuse another running owner's socket/state or kill its resources. Port conflicts must be resolved explicitly; no unrelated process is automatically stopped.

After verification/rollback and explicit owned-laboratory restoration/cleanup have settled:

```bash
.venv/bin/python scripts/manage_app.py --config config/local.json --dashboard-port 8501 stop
```

Then stop only your foreground agent with Ctrl+C. Do not use global `mn -c`, delete databases or interrupt an active campaign to clean this project.

## Teacher demonstration

A fresh clone has **no dataset, registered model, incident history or academic package**. Obtain/generate trusted artifacts as described in [PUBLIC_ARTIFACTS.md](docs/PUBLIC_ARTIFACTS.md). Missing or incompatible models must remain visible; rules/observed-only results cannot be relabeled as trained recovery.

1. Open Live Network and verify the selected backend/store, agent readiness, Recommend mode and automatic repair OFF. Expand **Guided teacher demonstration** and explicitly prepare an owned network.
2. Choose latency, start healthy traffic and monitoring, wait for fresh complete windows, and capture the healthy nominal reference. Workloads/collectors are bounded15minutes; read expiry/countdown and renew healthy state only when permitted.
3. Stop nominal monitoring/workload using the guided controls. Confirm the supported latency fault and restart monitoring. Keep the comparable fault workload and impairment active during subsequent verification.
4. On Diagnosis inspect this network/session's actual symptoms, rules, IF/RF support/calibrated prediction and matching ready SHAP. Unsupported, stale or incomplete evidence is a blocker.
5. On Twin & Recovery explicitly run validation and two-repair comparison. Inspect observed reconstruction uncertainty, source/twin metrics, no-change fidelity, repetitions, protected traffic, feasible alternatives and exact rejection reasons. Expect minutes, not a sub-ten-second complete decision.
6. Only if every backend gate passes, select Assisted mode, review/confirm and apply the eligible repair. Inspect two settled **original** verification windows, transient disruption and any rollback. Twin-only improvements do not prove original recovery. Original actuation is limited to qualified rerouting; generated shaping/QoS candidates do not establish supported original application.
7. Use explicit Undo/restoration when requested, then scoped cleanup of the selected owned instance. Do not clean automatically at the end of a teacher demonstration. Keep automatic repair disabled; laboratory automatic actuation is a later explicit-consent extension, outside the original research scope.

## Tests and contributing

```bash
# Fast non-laboratory fixtures; do not run privileged experiments on an active host.
.venv/bin/python -m pytest tests/test_foundation.py tests/test_agent_response_frames.py -q
```

Broader tests are in `tests/`; inspect requirements before executing native integration/campaign scripts. Software fixtures do not establish packet efficacy. Source, tests and manifests are public; local captures/logs, executable models, databases and large generated reports remain private/ignored. No license or institutional approval is implied.
