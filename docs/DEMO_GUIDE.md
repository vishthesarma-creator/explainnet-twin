> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# ExplainNet Twin demonstration guide — Stage 14

This guide covers the existing WSL environment, one bounded live laboratory rehearsal and a recorded fallback. Main dashboard: `http://127.0.0.1:8501`. The fresh rehearsal has a separate ordinary-user API/data store/dashboard on `http://127.0.0.1:8502`, and a separate root socket/state directory. It attaches no physical network interface.

## A. Startup and readiness

From an ordinary Ubuntu/WSL shell:

```bash
cd '/mnt/c/Users/Dell/Desktop/CN project'
.venv/bin/python -m pip check
/usr/bin/python3 -c 'import mininet, platform; print(platform.python_version())'
ovs-vsctl --version
tc -V
iperf3 --version
.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json check
.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json start
.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json status
```

The verified machine uses Python 3.14.4, Mininet 2.3.0, OVS 3.7.1 and iperf3 3.20. The existing venv/pins are reused. A clean-machine installation was not tested. `init` is additive if migrations are needed; never delete a database.

Expected main readiness: API worker, one compatible registered calibrated model, saved real SHAP and a complete 240/60/60 main split. An unavailable root agent is expected during recorded review. Separate cards distinguish agent, network, collector, model and explanation readiness. A healthy API alone proves none of the other prerequisites.

Manual labs use the separate root-agent command in README, with OS Python, UID 1000 and the selected socket. Leave failure hooks disabled. API/UI stay unprivileged. Starting services creates no network or automatic repair.

### Start the bounded live rehearsal

```bash
sudo env PYTHONPATH=src /usr/bin/python3 scripts/rehearse_stage14.py --detach
```

Verified host equivalent from PowerShell:

```powershell
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src /usr/bin/python3 scripts/rehearse_stage14.py --detach
```

The command prints TAG, supervisor PID and report path. Open port 8502 during execution. It refuses an occupied UI port and shares the sequential experiment lock. It never kills an unrelated listener. Review `artifacts/stage14/rehearsals/TAG/plan.json`, written before the first packet experiment.

Declared scope: five switches, 8 Mbps critical / 5 Mbps bulk UDP, 1200-byte packets, high one-way latency, native receiver streaming, 900-second traffic bound, 600-second collector, unchanged pilot fidelity and verification/rollback gates. There is one attempt per command, no automatic retry, and a 1400-second driver budget. Historical qualified primary runs took about five to six minutes, plus UI/Undo/cleanup; the actual saved integration report supplies this rehearsal's outcome and durations.

The isolated rehearsal deliberately has no activated classifier and uses the qualified **observed-only** scope. Actual canonical model/SHAP evidence is shown separately in section D. It does not unload a model after a rejection or claim an uncertain trained prediction permits actuation.

## B. Healthy operation

Open Network & Telemetry on port 8502. Show the actual owned five-switch definition, both paths, capacities and fresh timestamps. `config/stage14_traffic.yaml` supplies exactly 8/5 Mbps UDP. Two ten-second nominal captures establish the measured baseline and frozen fidelity policy.

Expected primary RTT is approximately 6.2 ms. Delivery should be near offered rates, subject to actual quality gates. Missing values stay unavailable. The healthy workflow must refuse with `service acceptable`; connectivity and this refusal are saved. Main-dashboard saved sources remain historical.

Talking point: “A symptom-free service should not be changed just because an anomaly score exists.”

## C. Fault detection

The separate `stage14_rehearsal_driver.py` invokes only the laboratory setup endpoint to introduce latency and keep traffic active. Injector labels are stored in `ground_truth`; diagnosis, reconstruction and candidate requests receive observed state and registered nominal references.

Expect primary RTT around 66 ms. The coordinator independently captures two fresh persistent violating windows and creates an observed incident. Show its actual incident/window IDs, UTC times and progress. Detection, inference/explanation, twin and action times are separate from total experiment duration.

Talking point: “The controller sees delayed packets and observed topology; it does not receive the injector's answer.”

## D. Diagnosis and explanation

Use the **main** dashboard's Incidents & Diagnosis/Evidence pages for real recorded trained predictions and matching model/window SHAP. `artifacts/stage13/backend_shap.json` identifies five measured **validation** examples and model `m20261016T074751_a92c0db8f44e`; these are not live rehearsal predictions. The main backend also retains measured training-window compatibility checks. SHAP uses training-only background and explains raw RF output, not calibrated confidence or physical cause.

On port 8502 show the **observed-only laboratory** label and the isolated backend's unavailable classifier/SHAP. Do not replace it with heuristic confidence. The separate Stage 13 trained live attempt had fresh calibrated confidence 0.9405 but remained uncertain and was refused; corroboration, fidelity and action gates still mattered.

Talking point: “A ten-episode held-out score is narrow evidence. Actuation still needs current service, freshness, explanation, fidelity and ownership.”

## E. Twin and recommendation

Open Digital Twin & Recommendations. Identify original instance, snapshot/time/expiry, frozen policy and separate twin ID/runtime. Show no-change controls, measured candidates and rejection reasons. At most one repair is tested across at most two hypotheses, with two matched repetitions per hypothesis; these are not independent source episodes.

The candidate moves the critical pair to its declared alternative route. Every required repeat/control and hard constraint must pass. A fidelity/quality refusal is valid. An old success grants no current permission. Backend applicability is read without saving/changing a workflow and explains disabled Apply controls when evidence is uncertain, expired or unavailable.

## F. Assisted recovery

Only after an eligible recommendation does the driver explicitly select Assisted Repair plus observed-only opt-in, briefly pause for inspection, and request one application through the normal API. Automatic repair stays off. Backend/root ownership, lineage, freshness, version, budget and rollback gates remain active.

Traffic and impairment stay active through verification. A qualified repair should yield two fresh settled original windows near 8 Mbps critical / 5 Mbps protected bulk and roughly 4.2 ms critical RTT. Compare twin predictions with actual original measurements. Show application-overlap disruption separately: forwarding updates may lose packets and are not atomic across all switches.

A submitted job is not a verified repair. Wait for the actual action outcome. Never clear the physical fault to manufacture success.

Measured rehearsal `207c58ab` ran from **2026-10-19T11:42:48.826466+00:00** to **2026-10-19T11:49:42.911402+00:00**. It verified 67.112 → 4.229 ms RTT in two settled windows, about 8.001 Mbps critical / 5.000 Mbps bulk, with zero measured settled UDP loss. The twin predicted 4.175 ms. Application took 955.53 ms. Separately, whole native intervals overlapping application had 136/1717 critical packets lost (7.92%) and 0/1042 bulk packets lost over approximately two seconds. Those intervals include adjacent traffic; they do not establish instantaneous loss or seamless forwarding. Complete rehearsal/Undo/UI/cleanup took 414.08 seconds.

## G. Audit and restoration

Open Recovery & Audit. Link incident → workflow → snapshot/experiment → action → original post-windows. Show journal/readback, modes, policy versions, UTC and monotonic times, settled measurements and transient disruption.

After success the script checks Undo applicability, explicitly requests Undo and saves a fresh restored observation. Undo restores previous owned forwarding while retaining impairment/demand. The report distinguishes **verified repair followed by intentional Undo** from failed verification/automatic rollback.

The script then stops new automation, stops the collector, resets only its scenario, cleans its own instance and shuts down only its child API/UI/agent. The supervisor compares bridge sets and socket removal. Reports, stopped database and root journals are retained. Manual cleanup uses the README order; inspect each job's actual terminal result and keep the agent available until verification/rollback finishes. Never use global cleanup or database deletion.

## Recorded fallback

If live prerequisites fail, use main Evidence downloads for Stage 13 and Stage 14. Identify saved run IDs and UTC timestamps. Example: Stage 13 source `s13_primary_1_f8f3f15d`, workflow `w6e2b1672f2904a81a0ab407658b4fe4d`, action `ab15e199eac304440aaf7d5ad6eb4c119` ran from **2026-10-19T10:15:22.955374+00:00** to **2026-10-19T10:21:08.947606+00:00**. It measured approximately 66 ms before and 4.29 ms after with about 8 Mbps critical delivery. Full evidence remains in `artifacts/stage13/labs/492fca67/report.json`. This is **recorded evidence**, not live telemetry or an executable recommendation.

After a rehearsal supervisor has exited, its persistent Linux backend history can be browsed using the printed TAG:

```bash
.venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/TAG/config.json --dashboard-port 8502 start
.venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/TAG/config.json --dashboard-port 8502 status
# After recorded review:
.venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/TAG/config.json --dashboard-port 8502 stop
```

It restarts with automation/exception disabled and no root agent; sources/actions are historical. Do not reuse expired recommendations. Moving to another machine needs deliberate data/config relocation from the backup; clean-machine restoration was not tested.

| Symptom | Action |
| --- | --- |
| Port occupied | Inspect port/receipt. Choose another explicit port or stop your known service. |
| Agent unavailable | Start the separate OS-Python agent/socket; recorded views still work. |
| Stale/incomplete | Inspect collector age, coverage/probes, receiver timing and resources. Preserve nulls and refusal. |
| Fidelity/no-safe-repair | Show actual control residuals/hard constraints; do not lower thresholds. |
| Model uncertain / SHAP missing | Show actual status and model/window. Use only clearly labeled supported scope or recorded evidence. |
| Ambiguous timeout | Inspect the existing receipt/job; do not submit a second independent action. |
| Interrupted application | Leave the agent available for reconciliation/rollback. Restart does not replay mutations. |

`artifacts/integration_validation_report.json` summarizes actual checks/rehearsal and retained failures. All six pages use supported Streamlit testing when browser automation is unavailable; no pixel-level/browser layout verification is claimed. Stage 15 and the final presentation remain outside this stage.
