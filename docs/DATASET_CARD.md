> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# ExplainNet Twin initial dataset

**Completion3 addendum (28 October2026):** the historical360-window card below remains separate. A new prospective3600-window cohort is collecting under `artifacts/completion_stage3/protocol.json`; it is not ready until all600 independent episodes and final quality/provenance audits finish. Its separate10-window pilot passed. See `COMPLETION_STAGE3.md` for actual current counts/families/splits, rejections, ETA and resume. No synthetic copies/pilot rows are counted; the new holdout is unopened for model development.

Collection software: implemented. Collection state: **completed**.
Dataset ready / Stage 7 gate: **True**.

## Measured size and provenance

Accepted windows: **360 / 360**.
Independent completed episodes: **60 / 60**.
Class counts: `{'healthy': 72, 'latency': 72, 'loss': 72, 'qos': 72, 'saturation': 72}`. Partitions: `{'train': 240, 'validation': 60, 'test': 60}`.
Rejected windows: 607; full reasons, missingness and shortfalls are in the quality report.

These are emulator-generated measurements from the fixed five-switch/six-host Mininet topology, OVS 3.7.1 and Linux tc. UDP/TCP receiver measurements come from installed iperf3 3.20; there are no manufactured, repeated, perturbed or oversampled rows. One independent network/namespace is created per episode attempt. UTC phase boundaries come from actual application/reset receipts; local monotonic intervals determine counter rates. Only wholly steady, complete inference-ready ten-second windows enter the feature table. Successful application and restoration are required before membership is committed. Failed attempts are retained separately.

## Faults and controls

Labels: healthy, saturation, loss, latency, qos. Saturation offers more than the fixed 100 Mbps shared capacity using h5→h6 background traffic. Loss is 3/8/15% netem impairment; latency adds 15/35/60 ms with supported reverse direction and optional 3 ms variation. These impairments use s2→s3 (and s3→s2 for bidirectional recipes). QoS restricts critical s3→s5 service to 0.8/0.5/0.3 Mbps under matched competing traffic, while the physical parent remains 20 Mbps. Healthy families include matched competing QoS and 70 Mbps background high-utilization controls with acceptable critical service.

## Collection and reserved splits

The predeclared compact schedule has 12 episodes per class, six accepted windows each (360 target). Each episode declares 85 seconds of measurement to allow five-second settling, window alignment and rejection overhead. Baseline/recovery controls each measure eight seconds, with two-second native omitted warmup. Actual pilot timing informed the estimate; approximately two hours plus resource-dependent overhead are expected for the batch. Episodes run sequentially under an experiment lock. One bounded retry preserves failed raw evidence.

Each class has six recipe families with two repetitions. Four families train, one validation, one test: **40/10/10 episodes**, or **66.7/16.7/16.7%**. Related recipes, all baseline/recovery records, and all windows from an episode inherit one partition. Evaluation reserves distinct load/packet size/direction combinations. The five-episode pilot is separate from the sealed main test set. Optional expansion declares 600 episodes / 3,600 windows and is not launched automatically.

The original declaration remains reserved. Current explicit recovery amendment: `linux_storage_v5`. Its full checksummed content/history is in the manifest; it may extend bounded collection time/attempts and declare sampler cadence. Actual collector settings remain in raw/storage provenance. Coverage, required receiver/probe gates, target windows and family/episode partitions remain enforced. Sampling cadence changes are a dataset limitation to retain in evaluation.

## Inputs, labels and structural checks

Features are the unchanged 21-column Stage 5 allowlist; units and sources are documented in `TELEMETRY_USAGE.md`. `window_id` is CSV metadata, not an input. All other IDs, timestamps, scenarios, severity, seeds, injection settings, filenames and partition labels are excluded from inputs. Missing optional RTT/jitter/class metrics remain null. Labels, split manifests, raw-source provenance and episode receipts are separate exports. No imputation, scaling, feature selection or model fitting has occurred.

Structural checks currently passed: **True**. They verify unique membership, schema/units, raw hashes/index alignment, raw reconstruction of accepted features, actual phase/ground-truth alignment, episode/family isolation and absence of cross-partition duplicate measurement sources. Test handling is structural only; future model development must use training/validation partitions. The quality report records explicit class shortfalls rather than dropping failed classes.

## Limitations and reproduction

This is a course-project emulation dataset, not production-scale evidence. Only supported fixed fault locations are varied in direction; arbitrary fault locations are not claimed. Workload/class correlation and emulator scheduling remain possible confounders despite matched controls. Seeds are recorded where supported but do not promise identical packet sequences. Resource pressure covers the Linux VM, not Windows. Receiver intervals arrive at completion; transition and partial windows are excluded. Exact state/counts/checksums are authoritative in `/home/USER/.local/share/explainnet/stage13/data/datasets/db5a15991774142f0a8ef871522face4d/manifest.json` and `artifacts/dataset_quality_report.json`.

See `DATASET_USAGE.md` for plan, status, cancellation, resume and export commands. Stage 7 may begin only when the main manifest reports `dataset_ready: true` and all required quality checks pass.
