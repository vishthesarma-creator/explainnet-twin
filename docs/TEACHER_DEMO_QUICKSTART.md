> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# ExplainNet Twin teacher demonstration

The current launcher/lifecycle contract is [Completion Stage 1](COMPLETION_STAGE1.md), dated 28 October 2026 IST. The default normal profile is trained on 8501; the observed-only profile must be selected explicitly on 8502. The older timed session IDs below are historical. Use the current receipt/status before presenting measurements.

**Current request: leave the healthy laboratory running.** Use [the manual live-session guide](TEACHER_DEMO_LIVE_SESSION.md) on **http://127.0.0.1:8502**. It binds commands/UI to the same existing observed-only store, leaves the healthy original/traffic/collector running, and separates fault, recommendation, assisted application and explicit cleanup. The older automatic rehearsal below includes cleanup and must not be launched for this current session. Port 8501 remains the separate trained-model application.

Prepared **21 October 2026** for **22 October 2026**, using Asia/Calcutta time. Stored experiment timestamps are UTC.

**Readiness: ready with limitations.** The missing privileged agent is now connected and a real original network, traffic, collector, current model inference and matching SHAP were tested. The fresh fault rehearsal correctly **refused** original repair because a repeated twin control failed fidelity. A complete live repair tomorrow is conditional on those same gates. Section C provides an honestly labeled recorded successful repair.

## What the two browser tabs mean

| URL | Use |
| --- | --- |
| **http://127.0.0.1:8501** | Main application, preserved dataset/model, healthy live check and saved explanations. |
| **http://127.0.0.1:8502** | Temporary isolated observed-only UDP latency demonstration, available only while its supervisor is running. |

The main configuration's healthy traffic is **2 Mbps critical UDP plus configured 5 Mbps bulk TCP**. The qualified fault driver uses **8 Mbps critical plus 5 Mbps bulk, both UDP**. Do not describe these as the same experiment.

# A. Prepare before the teacher arrives

Allow 10–15 minutes. Keep your laptop awake and plugged in. Run only one fault rehearsal at a time. Avoid starting training, collection campaigns or other heavy work during twin measurements.

## A1. Start the existing API and dashboard

Open **Windows PowerShell**, called **Terminal 1** below. Paste:

```powershell
cd '/path/to/user\Desktop\CN project'
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json start
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json status
```

Expected: backend and dashboard `owned: true`, `ready: true`; mode `recommend`; `auto_enabled: false`; `allow_observed_only: false`. Existing owned services are reused. The command returns; these managed services run in the background. Keep Terminal 1 for later commands, but it does not have to stay open to keep them running.

Open **http://127.0.0.1:8501** in Brave. Click **Overview**, then **Refresh now** in the sidebar. The first page can take tens of seconds to finish loading; the measured six-page functional check's first page took about 42 seconds including initialization.

Say: “This dashboard reads the real backend. Model readiness, the network and repair permission are checked separately.”

## A2. Connect the privileged agent only if needed

If **Privileged agent** already says **Connected**, skip this command. The preparation session started it in the background on the existing configured socket. Do not start a second copy.

If it says **Unavailable**, open another **ordinary Windows PowerShell**, called **Terminal 2**, and paste:

```powershell
cd '/path/to/user\Desktop\CN project'
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src /usr/bin/python3 -m explainnet.agent_server --allow-uid 1000 --socket /run/explainnet-stage6-38223/agent.sock --state-dir /var/lib/explainnet-teacher-demo --stream-receivers
```

**Leave Terminal 2 open.** The agent is a foreground server and normally waits quietly without returning a prompt. In Brave, click **Refresh now**. Expected: **Privileged agent: Connected** within a few seconds. Starting it does not create a network. If the terminal says `agent already running`, use the existing agent and refresh; do not kill it or delete its socket.

This verified Windows/WSL command needs no password entry. The API/UI remain ordinary-user processes; OS `/usr/bin/python3` runs the privileged agent separately.

Say: “The separate Linux agent owns only our emulated network. It does not attach to the physical Wi-Fi or LAN.”

## A3. Run the short healthy check

Open **Network & Telemetry** once before the commands below and let the page finish loading. With no network, its empty state is expected. After the helper starts a network, the first topology chart may need up to a minute for browser assets; the actual chart was checked in Brave. If the traffic expires while the first chart loads, repeat the two commands below and revisit the loaded page.

In **Terminal 1**, first clean only any previous healthy-check instance, then create a fresh one:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/check_teacher_demo.py --cleanup
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/check_teacher_demo.py
```

`--cleanup` uses its own saved instance receipt. With no prior receipt it does nothing. Do not substitute another instance ID. The check creates one original, probes h1 to h3, starts 100-second healthy traffic and a 120-second collector, waits for a suitable complete window, then requests current inference and SHAP through existing APIs. It never injects a fault or applies a repair.

Expect job IDs followed by the new instance/window IDs and actual results. The measured operation phase took **22.63 seconds**, plus initial model/library loading. Allow roughly 30–90 seconds on a cold start. The command returns; Terminal 1 need not stay open.

Immediately in Brave:

1. Click **Overview**, then **Refresh now**. Expect **Privileged agent: Connected** and **Verified active originals: 1**.
2. Click **Network & Telemetry**. In **Original laboratory**, select the `teacher_...` ID printed by the helper.
3. Turn on the sidebar **Refresh active view every 10 seconds**, or click **Refresh now**.
4. Show the actual topology, mean RTT, critical delivered rate, window ID, UTC and quality. A complete window needs about ten seconds. Missing values must stay unavailable.

**Fresh means the collector is still running and the observation is recent.** Traffic stops after 100 seconds and the collector after 120. `Historical / stale` after that is expected, not a live healthy claim. For a new check, run the two A3 commands again.

The corrected dashboard shows the latest completed window from the current collection while its next window accumulates. Quality failures remain visible. In Brave at **21 October 03:32:39 UTC**, window `w7f3343cd4021fb5e70fde811ac031109` visibly showed **Fresh**, **15.22 ms RTT**, **2,000,002 bps** critical delivery and **0.00%** measured receiver loss. That is recorded proof of this check, not a promise that tomorrow's values will match. Open the home URL first and use its named sidebar links after a UI restart.

Say: “These values came from receiver events, ping probes and counters. The UTC and window ID identify the actual measurement.”

## A4. Show current diagnosis and explanation honestly

The existing bundle was loaded and checked: model `m20261016T074751_a92c0db8f44e`, 21 numeric features, five classes, compatible dependencies and calibration present. The ten older ready explanations were saved evidence; new ones were added during the current healthy check.

To show this check's own result in **Terminal 1**:

```powershell
$healthy = Get-Content '.\artifacts\teacher_demo\latest_live_check.json' -Raw | ConvertFrom-Json
$healthy.diagnosis | ConvertTo-Json -Depth 8
$healthy.current_explanation | Select-Object status,explanation_id,window_id,model_id,created_utc,runtime_ms | Format-List
$healthy.current_explanation.result.contributions | Sort-Object @{Expression={[math]::Abs($_.contribution)};Descending=$true} | Select-Object -First 5 transformed_feature,contribution
```

Measured example: window `w536f3d6dde4220ae40d844a3b29577f2` had RTT **12.19 ms**, critical delivery **2,000,007 bps**, predicted class **healthy**, calibrated confidence **0.5841**, and status **uncertain** because confidence was below policy. Its matching explanation `xc29c257e179b4f4283a5cef5d55ce28d` became **ready**, taking **346.83 ms**. New runs have new IDs and may produce different results.

Say: “The trained model is usable, but this prediction is uncertain. SHAP explains its raw forest output; it does not prove a physical cause or grant repair permission.”

## A5. End the healthy check before the fault demonstration

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/check_teacher_demo.py --cleanup
```

Expected: `Cleaned only teacher_...`. The main agent/API/UI stay available; no healthy-check traffic or bridge remains. This avoids competing traffic during the isolated fault trial.

# B. Perform the live demonstration

## B1. Start one bounded observed-only trial

In **Terminal 1**:

```powershell
$demo = wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src /usr/bin/python3 scripts/rehearse_stage14.py --detach | ConvertFrom-Json
$tag = $demo.tag
$demo | Format-List
```

This is the existing test supervisor, not a new project. **Running this command deliberately authorizes one assisted, observed-only laboratory trial.** It starts its own separate root agent and ordinary-user API/UI/store. Its written `plan.json` declares the scope before packets. It does not unload the canonical trained model or retry a refusal.

The command prints `supervisor_pid`, `tag` and `report`, then returns. Its child runs in the background, so Terminal 1 need not stay open. Keep `$tag` for inspection. Open **http://127.0.0.1:8502** after about 10–30 seconds. This port must be free; if occupied, inspect the known service instead of killing a process.

The driver performs the sequence below automatically. **Do not click a second Apply, inject another fault, change its mode or start a second workflow while it is running.** Automatic repair remains disabled. The explicit observed-only exception is enabled only inside this isolated trial and cleared afterward.

## B2. Follow the actual pages

| Phase | Click or observe | Expected observation and teacher narration |
| --- | --- | --- |
| Healthy | **Overview**, then **Network & Telemetry**. Select `demo14_` followed by `$tag` in **Original laboratory**. Enable **Refresh active view every 10 seconds**. | Five switches, six hosts, 8 Mbps critical / 5 Mbps bulk UDP. Today healthy RTT was 6.253 and 6.248 ms. “The healthy control should refuse an unnecessary change.” |
| Fault | Stay on **Network & Telemetry**. The **separate test driver** submits the bounded laboratory latency setup. | Today impaired RTT was 66.218 ms. “The injection label is separate ground truth; diagnosis receives observations.” Do not use the UI's short **Inject fault** form for this multi-minute experiment. |
| Incident and diagnosis | **Incidents & Diagnosis**. Select the incident belonging to `demo14_$tag` in the **Recorded incident** selector. | Two persistent fresh violating windows establish the incident. Show symptoms and **Rule-based findings**. “This repair trial uses observed rules and measurements. The trained model and matching SHAP we showed in tab 8501 are separate.” No SHAP is invented for this untrained isolated store. |
| Twin | **Digital Twin & Recommendations**. Select the current **Candidate experiment**. | Show source snapshot, separate twin, hypotheses and **Measured candidate comparison · twin only**. Each action uses a fresh reset and matched no-change control. Two repeats are required for each hypothesis. “A matching topology does not prove packet fidelity.” |
| Eligibility | **Recovery & Audit**, then select **Recorded recovery workflow** for this source. | **Current backend mode** initially Recommend; **Automatic actuation** stays Disabled. The visible **Enable observed-only laboratory exception** corresponds to explicit consent already given by the driver command. **Apply eligible repair** must remain unavailable if a gate refuses. |
| Assisted application, only if eligible | Remain on **Recovery & Audit**. The driver selects **Assisted Repair**, checks backend applicability, pauses five seconds and submits exactly one assisted action. | No manual duplicate click is needed. If the driver were not submitting, the real UI requires **I confirm this proposed repair on the identified original laboratory** before **Apply eligible repair**. “A recommendation is a prediction; we now check the original network.” |
| Verification and restoration, only after success | Inspect **Original action history** and **Action verification detail**. | Two fresh original windows must qualify while traffic and impairment remain active. Show settled RTT/delivery/loss separately from **Application disruption · separate from settled verification**. The driver then checks applicability and performs intentional Undo. “Undo restores the old route while the physical impairment stays active.” |

The UI's **Qualified baseline JSON** and **Frozen fidelity policy JSON** fields under **Recommendation workflow / monitor** are for a separately prepared manual workflow. This driver builds their actual measured values. Leave those fields alone for this demonstration. Do not copy an old policy/snapshot into a new action.

## B3. Waiting times and checking progress

Today's fresh trial took **218.05 seconds (3 min 38 s)** for the driver through refusal, page checks and cleanup. Detection observations took **22.37 s**, diagnosis submission **3.81 ms**, snapshot capture **17.12 s**, twin construction **5.87 s**, and candidate testing **76.21 s**. Each matched trial includes reconstruction, warmup and a measured window. The earlier fully successful case took **414.08 s (6 min 54 s)** including verification, Undo and cleanup. Allow about **4–8 minutes**, conditional on actual gates and host timing; these are observations, not a success guarantee.

To inspect current progress in **Terminal 1**, repeat:

```powershell
$run = Get-Content ".\artifacts\stage14\rehearsals\$tag\report.json" -Raw | ConvertFrom-Json
$run | Select-Object tag,status,instance_id,started_utc,ended_utc,error | Format-List
$run.progress | Select-Object -Last 4 at_utc,state,collector_samples,health_response_ms
$run.workflow | Select-Object workflow_id,state,reasons | Format-List
```

The report may not exist during the first startup seconds. Wait briefly instead of rerunning the launch command. Its final `status` is authoritative. The supervisor has a finite 1400-second driver deadline and does not silently retry.

## B4. What actually happened in this preparation session

Run **bb745a91**, source **demo14_bb745a91**, executed **20 October 2026 19:05:15 UTC** (21 October 00:35:15 IST):

- Connectivity and healthy refusal passed; impaired RTT reached **66.218 ms**.
- The first no-change twin control passed and one twin reroute measured **4.282 ms**.
- The next required no-change control failed RTT-variability fidelity: original **0.0745 ms**, twin **6.5853 ms**, allowed difference **3.0373 ms**. Raw ping included a real **94.4 ms** sample.
- Final workflow: **refused**, `twin recommendation not eligible: insufficient-evidence`. There was **no original application, post-repair verification, Undo or application-loss measurement** in this run. Those missing results are null, not zero.
- The refusal and all trial records were retained. Cleanup passed, no rehearsal bridges/socket remained, and automation/exception ended off. A valid fidelity refusal was not treated as a software defect or retried until success.

Say: “Today's run refused because its twin control was too variable. That is the implemented gate working. I will show the earlier verified original repair as recorded evidence.”

# C. Use clearly labeled recorded evidence

Use this if the live environment is unavailable or the live trial refuses. This is the recommended fallback for the complete repair story.

1. Open **http://127.0.0.1:8501** and click **Evidence & Project Information**.
2. Find **Stage 14 integration** in **Approved evidence library**. Read the recorded source/time/outcome and, if useful, click **Download approved summary** within that card.
3. Show historical run **207c58ab**, executed **19 October 2026 11:42:48–11:49:42 UTC**. It verified original RTT **67.112 → 4.229 ms** in two settled windows, about **8.001/5.000 Mbps** critical/bulk delivery, then intentional Undo to **66.261 ms** with impairment still active.
4. State that whole intervals overlapping application lost **136/1717 critical packets (7.92%)**, while later settled windows measured zero UDP loss. These are different measurement periods.
5. The final report, page 19, has the recorded graph and measurements: `deliverables/ExplainNet_Twin_Final_Report.pdf`. The raw source is `artifacts/stage14/rehearsals/207c58ab/report.json`.

Say: “This is recorded evidence from October 19, not live telemetry. Today's refusal is retained separately. The earlier run proves only this qualified observed-only UDP latency case.”

## Troubleshooting

| Symptom | Exact next action |
| --- | --- |
| Agent unavailable | Use A2's Terminal 2 command and leave that terminal open. Refresh. Check that its socket matches `/run/explainnet-stage6-38223/agent.sock`. If it errors, read that terminal; do not delete a socket or enter a password into chat. |
| No live network | Agent startup alone creates none. Run A3, or B1 for the separate full trial. Port 8501 and 8502 are different backends. |
| Empty/stale telemetry | Select the correct original and refresh. Wait for a complete ten-second window. Healthy-check traffic/collector expire at 100/120 seconds; use A3 cleanup and a fresh check. Do not call an old window live. |
| Network page appears slow | Wait for the page and topology chart to finish, then navigate through the sidebar. All six functional pages passed, and the real topology chart rendered in Brave with no JavaScript errors. Its first asset load can take up to a minute. Preload it before A3; repeat A3 if the short traffic period expires during loading. |
| No incident | The healthy check may have no new fault incident. The isolated fault driver needs two violating windows; choose its own incident/source. Do not select an older incident as proof of this run. |
| Model uncertain or SHAP unsupported | Show its actual status/reason and matching IDs. `Active` and a count of saved explanations do not make a current diagnosis supported. Never disable a model after refusal to pass a gate. |
| Recommendation refused | Read workflow reasons and the failed control/quality evidence. Do not click Apply, lower tolerances or retry until it succeeds. Use section C. |
| Port 8502 occupied | Do not run a second supervisor or kill an unrelated process. If it is your known recorded-review service, stop it with its original `manage_app.py --config ... --dashboard-port 8502 stop`; otherwise use section C. |
| Need to stop a running workflow | On its own **Recovery & Audit** page use **Stop Automation** and **Cancel selected workflow** if offered. Keep the agent available until verification/rollback and the supervisor's scoped cleanup finish. Stop Automation alone does not Undo a kept repair. |

## Restore and shut down

The bounded fault supervisor normally resets its scenario, stops its collector, cleans its own original/twins and shuts down its child services. Wait for `supervisor.json`:

```powershell
Get-Content ".\artifacts\stage14\rehearsals\$tag\supervisor.json" -Raw
```

Expected: `owned_bridges_removed: true`, `preexisting_bridges_preserved: true`, `socket_removed: true`. This describes only the rehearsal's resources. Do not close its root owner during pending verification/restoration.

For the separate healthy check:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/check_teacher_demo.py --cleanup
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/explainnet --config artifacts/stage6/runtime/config.json lab-control
```

Confirm `auto_enabled: false`, `allow_observed_only: false` and no active workflow. If you deliberately changed those main settings, use **Recovery & Audit → Stop Automation**, select **Recommend**, uncheck **Enable observed-only laboratory exception**, then **Apply mode selection**, and confirm the actual readback.

After all actions and owned network cleanup finish, stop managed API/UI if desired:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json stop
```

For a foreground agent started in Terminal 2, press **Ctrl+C in that terminal last**. The preparation session's already-running background agent may be left idle for tomorrow; closing Terminal 1 does not stop it. WSL shutdown stops it, so A2 is needed after a restart.

No fault or kept repair is left after this preparation. The healthy source is cleaned at handover, with the main API/UI and agent ready. **Start a fresh network using A3 or B1 for the next demonstration.** Old snapshots, recommendations and action IDs must not be reused. Never use global `mn -c`, indiscriminate process kills or database deletion.

Measured handover at **21 October 03:34:40 UTC**: no OVS bridges, both temporary healthy originals stopped, no active workflow, Recommend mode, auto-repair off, observed-only exception off. The root agent identity/socket and scientific artifact hashes passed checks; managed API/UI were ready. After a computer/WSL restart, begin again at A1 and A2.

## Evidence locations

- Fresh fault trial and archived native evidence: `artifacts/stage14/rehearsals/bb745a91/`.
- Healthy check and current model/SHAP: `artifacts/teacher_demo/healthy_checks/20261020T202933Z_7ea3/report.json`.
- Latest healthy-check receipt: `artifacts/teacher_demo/latest_live_check.json`.
- Startup/model/browser/functional checks and final handover: `artifacts/teacher_demo/20261021/`.
- Historical complete successful repair: `artifacts/stage14/rehearsals/207c58ab/`.
- Saved dataset, model and evaluation artifacts remain unchanged; no retraining or test rescoring was performed.
