> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Stage 1 environment

## Stage 14 lifecycle and rehearsal storage

The existing working WSL/app environment is reused with local package metadata 0.14.0; pinned runtime dependencies are unchanged. `scripts/manage_app.py --config CONFIG check|start|status|stop` runs only ordinary-user API/UI components. Its receipt/logs live in the configured runtime directory and validate PID start ticks, UID, cwd and argv before stopping a process. The root agent remains a separate OS-Python command. No clean-machine installation or cross-machine restoration was tested.

Stage 14 rehearsal `207c58ab` uses its own persistent Linux data directory declared by `artifacts/stage14/rehearsals/207c58ab/config.json`; the canonical Stage 13 data/model directory below is not merged or replaced. A stopped database/root-journal evidence archive is retained beside that config. The rehearsal supervisor removed its own bridges/socket/processes, left automation/observed-only flags off, and preserved unrelated resources. See `DEMO_GUIDE.md` for exact live and recorded-review commands. Temporary archive-inspection copies are automatically removed and are not a handover package.

## Stage 13 hot-data storage (2026-10-16)

The source workspace remains `/mnt/c/Users/Dell/Desktop/CN project`. After a measured collection coverage failure, the authoritative application data directory moved to `/home/USER/.local/share/explainnet/stage13/data`. `artifacts/stage6/runtime/config.json` now declares that path. Code, the application venv, runtime configuration and reviewable reports remain in this workspace. The privileged agent still uses OS Python and a separate root state directory.

The old Windows-mounted database and raw files are retained. `artifacts/stage13/storage_relocation.json` records byte hashes for every copied file and preservation of all 192 existing accepted main members. `collection_timing_diagnosis.json` records actual agent/sampler timing and separate storage measurements (20 SQLite commits: Windows mount mean 37.3 ms; Linux mean 0.15 ms). No scientific feature, label, split or quality threshold was changed by moving storage. Use commands that read the configuration; older scripts that hardcode `runtime/app/data` refer to the preserved historical store.

Recreate/resume with the recorded configuration and `scripts/status_stage13.py`; do not delete either database. Back up the new data directory and its SQLite database before moving machines. The compact exported dataset and final evidence archives are also retained under the project's artifact conventions.

Checked on 2026-10-07 (Asia/Calcutta).

## Machine and execution route

- Host: Windows 10.0.26200, x64, PowerShell 5.1; 8 logical CPUs visible. The current workspace is `/path/to/user\Desktop\CN project`.
- Existing runtime selected: Ubuntu 26.04 LTS on WSL2, Linux 6.18.33.2-microsoft-standard-WSL2, x86_64. It has 8 vCPUs, 7.6 GiB RAM, 2 GiB swap, and about 953 GiB free on its Linux filesystem. The current workspace appears at `/mnt/c/Users/Dell/Desktop/CN project` inside WSL. The Windows volume had about 289 GiB free at inspection.
- An older, separate `/home/USER/code/ExplainNet-Twin` directory already existed and was left untouched. No VM or additional virtualization stack was installed.
- The Mininet test created only internal virtual Ethernet links and OVS bridges; it attached no physical LAN or Wi-Fi interface.
- The ordinary WSL user is `USER`. Noninteractive `sudo` prompts for a password, but `wsl.exe -d Ubuntu -u root -- ...` can run the privileged networking agent. The agent must use `/usr/bin/python3`: that interpreter imports Mininet from `/usr/lib/python3/dist-packages/mininet`. The project `.venv` is separate for ordinary application code and does not import OS Mininet.

## Installed and verified

Ubuntu package tooling (`apt-get install -y python3-pip tcpdump`) added the only missing system tools. Existing Mininet 2.3.0, OVS 3.7.1, iproute2/tc 6.19.0, iperf3 3.20, ping, Git 2.53.0 and Python 3.14.4 were preserved. Installed package versions include `python3-pip 25.1.1+dfsg-1ubuntu2` and `tcpdump 4.99.6-1`. No global pip install was used.

The Linux application environment is `.venv` in the current project. `requirements.txt` pins its direct dependencies. Recreate with:

```bash
cd '/mnt/c/Users/Dell/Desktop/CN project'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

All 16 direct packages imported with Python 3.14.4. `.venv/bin/python -m pip check` reported no broken requirements. Resolved versions are in `artifacts/application_imports.json`; run `.venv/bin/python scripts/check_app_env.py` to repeat the import check. The app venv does not import OS Mininet, as intended for the privilege boundary.

Run the packet smoke test from PowerShell with:

```powershell
wsl.exe -d Ubuntu -u root -- timeout 90 python3 scripts/check_environment.py
```

It saves `artifacts/network_smoke.json`. The two test networks have distinct Mininet names, same-VM internal dataplanes, and no external bridge. The script removes its own networks, flows, QoS and queue records without `mn -c`.

## Editor and path

The current editor can use the supplied Windows workspace. WSL commands launched from this folder inherit the `/mnt/c/...` project path. Linux filesystem placement is preferable for future sustained experiments: before Stage 2, copy this project to a **new** directory such as `/home/USER/code/ExplainNet-Twin-CN` and reopen that path through a WSL-aware editor. Do not overwrite the existing `/home/USER/code/ExplainNet-Twin`. The present Stage 1 evidence and tests were run from the Windows-mounted path; no root was silently changed.

## Smoke evidence

See `artifacts/network_smoke.json` for actual counters and iperf results. The final run passed OVS host connectivity, packet counters, two concurrent isolated networks, bounded TCP and UDP iperf3 with receiver jitter/loss fields, 40 ms netem delay with observed loss, and queue 1 packet counters after an OpenFlow `set_queue:1` action. Post-test checks found no remaining test bridges, QoS rows, queues or namespaces.

The first queue check parsed the text format incorrectly. Its evidence already showed 665 packets in queue 1. The parser was corrected, and the second full run passed with 203 packets in queue 1.
