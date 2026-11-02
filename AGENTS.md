# ExplainNet Twin development rules

- Work in the cloned project root; follow portable startup in `README.md`. Historical environment paths are anonymized. Keep the privileged Mininet agent separate from the unprivileged API and application venv.
- Use UTC for stored timestamps, monotonic clocks for elapsed durations, milliseconds for RTT/jitter, bits per second for rates, and fractions for loss/utilization. Preserve missing values as null.
- Never mix experiment ground truth into inference features. Store it only in `ground_truth` records.
- Use SQLite migrations; never delete an existing database during setup. Use bounded subprocess argument lists and isolated emulated dataplanes.
- Implement only the current requested stage. Keep future mutation operations unsupported until their verification and rollback stages.
- Run focused tests for changed code and update `docs/PROGRESS.md` with measured evidence and limitations.
