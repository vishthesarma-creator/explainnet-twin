> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Teacher demo: manual session left running

**28 October operational update:** use [Completion Stage 1](COMPLETION_STAGE1.md) for the normal launcher, read-only status/reconciliation, scoped stop and fresh-network commands. The IDs and October 21 expiry times below are historical. Read `demo status` and `artifacts/completion_stage1_validation.json` for the actual current original and bounded lifetimes. Direct routes/reloads now retain the shared refresh shell. Healthy renewal refuses an actual active fault, unsettled action or untracked traffic; no eligibility gate changed.

Prepared 21 October 2026. This is the current leave-running workflow. Do not launch `rehearse_stage14.py`: that older supervisor injects/applies/Undo/cleans automatically. Preparation here starts only healthy traffic; later stages require your commands or clicks.

## Open the correct application

**Open http://127.0.0.1:8502/ first**, then use its sidebar. The prepared original is **`teachlive_03f4798225`**. It is a real five-switch, six-host laboratory with 8 Mbps critical UDP and 5 Mbps bulk UDP, 1200-byte packets. Its healthy pilot RTTs were **6.315 and 6.366 ms**. Your next windows may differ.

| Item | Current repair demonstration |
| --- | --- |
| Dashboard | `http://127.0.0.1:8502` |
| Sidebar API URL | `http://127.0.0.1:43989` |
| Command configuration | `artifacts/stage14/rehearsals/bb745a91/config.json` |
| Evidence database | `/home/USER/.local/share/explainnet/stage14/rehearsals/bb745a91/data/explainnet.sqlite3` |
| Session receipt | `artifacts/teacher_demo/interactive/session.json` |

The managed process identities, running UI's API environment, an HTTP job's SQLite row, and the displayed window's source were verified. The old refused `bb745a91` experiment is preserved in this existing store. **Use your new session/workflow/experiment IDs**, not that older experiment.

**Port 8501 remains the separate canonical trained-model application.** Its model/dataset were preserved. This repair demo on 8502 is explicitly **observed-only**, using measured symptoms and rules; no classifier was disabled to obtain it. Trained-model actuation remains unqualified. An empty current candidate list is expected until step 4 actually runs. Historical candidate records do not authorize a new action.

## PowerShell commands

Open ordinary **Windows PowerShell**. Paste this function once; it binds all commands below to the verified session configuration:

```powershell
function demo { wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/teacher_demo_session.py @args }
demo status
```

Expected: original `running`, collector `live: true`, `same_store_window_verified: true`, mode `recommend`, `auto_enabled: false`, no current workflow yet. The receipt contains exact source/window IDs and expiry UTCs.

The full form, if you open another PowerShell without defining the function, is:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/teacher_demo_session.py status
```

## Five-step demonstration

### 1. Healthy live service

In Brave on **8502**, click **Overview → Refresh now**. Expect agent Connected and one verified active original. Click **Network & Telemetry**; select **`teachlive_03f4798225`** under **Original laboratory**. Enable **Refresh active view every 10 seconds**.

Show **Fresh**, actual RTT/delivery/loss, the UTC and window ID, and the selected primary route. Approximately 6.3 ms and 8 Mbps critical delivery were measured during preparation; do not present configured rates as measured delivery. A new complete window takes about ten seconds.

Say: “These are real receiver, ping and counter observations. No fault has been introduced.”

### 2. Introduce the supported latency fault

In the same PowerShell:

```powershell
demo fault
```

This separate setup stage stops the healthy traffic/collector, submits the existing bounded **high one-way latency** recipe with **8/5 Mbps UDP**, and starts a fresh 600-second collector. Traffic/impairment are bounded to about 900 seconds. Ground truth remains separate; the recipe is not included in diagnosis, snapshot baseline or candidate inputs.

Keep **Network & Telemetry** refreshing. Expect RTT around 66 ms, subject to real measurements. **Do not use the UI's 20-second Inject fault form**, change paths, or clear the impairment during later verification.

Say: “The controller receives observed degradation, not the injector's hidden label.”

### 3. Show the incident and actual diagnosis

Allow roughly **20–40 seconds** for two persistent complete violating windows. Click **Incidents & Diagnosis → Refresh now → Recorded incident** and choose the incident whose source is **`teachlive_03f4798225`**. Show its observed symptoms, supporting window UTC, state/severity and **Rule-based findings**.

The selector lists IDs. To identify this original's exact incident ID, run in PowerShell after the fault:

```powershell
(Invoke-RestMethod 'http://127.0.0.1:43989/v1/incidents?instance_id=teachlive_03f4798225').records | Select-Object incident_id,state,instance_id,last_window_id
```

The qualified healthy reference was explicitly registered; the existing 15 ms RTT reference margin and persistence gates remain unchanged. Missing/unsuitable windows may delay an incident. Do not select an old incident as this run's result.

There is no active classifier or real SHAP for this observed-only demo store. State that plainly. For trained-model evidence, port 8501 has the preserved active model and separately identified explanations, but those are a different backend and must be labeled separately. Step 4's workflow records its actual `diagnosis.status: observed-only` after its own fresh incident observations.

### 4. Run measured twin fidelity and candidate comparison

In PowerShell:

```powershell
demo recommend --observed-only
```

This is explicit consent to the existing observed-only exception. It keeps **Recommend** mode and automatic repair **off**, submits exactly one workflow using the two measured healthy baseline windows and their frozen fidelity policy, and waits for a recommendation or refusal. **It does not apply, Undo, reset the scenario, or clean the original.** Leave this terminal open until the command returns. UI inspection can continue in parallel.

Allow about **3–5 minutes**, depending on gates and host timing; the previous fault run ended in refusal after 3 min 38 s. The workflow has a 900-second limit. The terminal prints state changes, workflow ID, incident ID, experiment ID and reasons.

Click **Digital Twin & Recommendations → Candidate experiment** and select that **new experiment ID**. Show the immutable source snapshot, separate twin, matched no-change controls, hypotheses, repeated measurements and **Measured candidate comparison · twin only**. Click **Recovery & Audit → Recorded recovery workflow** for its diagnosis, state and reasons.

If refused, show the exact reason and stop before application. The latest earlier run failed a repeated no-change RTT-variability control despite one promising twin reroute. No thresholds, confidence, quality, ownership, freshness or rollback checks may be bypassed. Do not rerun until it happens to succeed.

### 5. Apply only an eligible assisted repair and verify

Only if the **new current workflow** is recommended and still eligible, use **Recovery & Audit**:

1. Under **Operating mode**, set **Requested mode → Assisted Repair**.
2. Check **Enable observed-only laboratory exception** and **I understand the exception uses observed rules/measurements, not trained AI**. Leave automatic-actuation consent unchecked.
3. Click **Apply mode selection**. Confirm **Automatic actuation: Disabled**.
4. Select the new **Recorded recovery workflow**. Read the proposed change and current applicability/rejection reason.
5. Check **I confirm this proposed repair on the identified original laboratory**, then click **Apply eligible repair** exactly once. A disabled button means a gate has not passed.
6. Wait for the actual job/action outcome. Inspect **Original action history → Action verification detail**. Success requires two fresh qualified original verification windows while demand and impairment remain active, with readback/connectivity and protected-flow checks. Inspect **Application disruption · separate from settled verification** separately; null is not zero.

The earlier successful recorded case settled near 4.2 ms; this is a comparison, not a claim or guarantee for your run. Actual verification failure must roll back and remain recorded. Do not clear the fault to manufacture a healthy result.

Say: “The twin proposes a change; the original network's fresh measurements decide whether it worked.”

## Expiry, terminals and keeping it live

**No end-of-rehearsal cleanup was run.** The original remains owned/running. Agent, API and UI were launched in the background; no PowerShell terminal must stay open after its command returns. Keep Windows/WSL awake and do not shut down WSL or its agent during verification/rollback.

Healthy traffic lasts **900 seconds**, collector **600 seconds** from its start. `demo status` and the session receipt give exact UTC expiry times. The network itself persists after these jobs expire; historical/stale values then are expected.

**Before injecting any fault**, renew the same healthy laboratory if necessary:

```powershell
demo renew
```

This restarts only its healthy traffic and collector for another 900/600 seconds, retaining the qualified baseline and network. Wait **10–20 seconds**, then Refresh now. It refuses after fault submission so it cannot erase a fault/repair verification. `demo fault` starts its own new bounded workload/collector; perform steps 3–5 promptly within that collector lifetime.

Renewal now reads the owned run's actual state before stopping it. Already completed runs are reconciled into the API store and are not stopped again. A 22 October failure came from a valid 2.65 MB completed-run reply exceeding the old 2 MiB client cap; traffic status/stop now have an 8 MiB bounded allowance while other replies retain their original cap. Full raw interval evidence is preserved. If another operation reports an unknown outcome, inspect its saved job and actual run before retrying; never assume the error means traffic remained running.

## Explicit cleanup after the demonstration

After a successful kept repair, while its current demand/impairment still exist, first use **Recovery & Audit**, select the original, check **I confirm undo of the backend-identified reversible action**, and click **Undo Last Lab Action**. Wait for the rolled-back action result. If Undo is unavailable or an action is unsettled/degraded, leave the agent running and inspect the stated blocker rather than forcing teardown.

Then run:

```powershell
demo cleanup
```

Equivalent full command:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/teacher_demo_session.py cleanup
```

This checks the session receipt and active/kept/degraded actions, returns to Recommend with exception off, stops only this collector, resets its owned scenario and cleans only its original. It preserves evidence and the unrelated canonical services. No global cleanup or database deletion is used.

To stop the **demo's** managed API/UI afterward, optionally run:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/bb745a91/config.json --dashboard-port 8502 stop
```

The separate root owner can remain idle. Restart instructions and its process receipt are in `artifacts/teacher_demo/interactive/`; a foreground agent terminal, if you start one later, must remain open until owned actions and cleanup finish.

## Existing service startup commands, if later needed

The components are already running now. If the demo agent is unavailable later, use a separate PowerShell **Terminal 2** for its foreground command and leave that terminal open:

```powershell
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src /usr/bin/python3 -m explainnet.agent_server --allow-uid 1000 --socket /run/explainnet-stage14-bb745a91/agent.sock --state-dir /var/lib/explainnet-stage14-bb745a91 --stream-receivers
```

Do not start a second agent if already connected. In ordinary PowerShell **Terminal 1**, start/check only the managed demo API/UI:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/bb745a91/config.json --dashboard-port 8502 start
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage14/rehearsals/bb745a91/config.json --dashboard-port 8502 status
```

These commands create no network and do not train or reset a database. After Windows/WSL restart, verify the actual network state; do not assume an old session is still live or reuse old candidate/action IDs.
