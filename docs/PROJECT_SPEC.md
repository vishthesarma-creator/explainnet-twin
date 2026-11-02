# ExplainNet Twin project specification

This document retains the original course target and roadmap. Current implemented capabilities, measured results and limits are in `PROJECT_STATUS.md`; Stage 14 does not start the final release or presentation.

ExplainNet Twin is a local Computer Networks laboratory application. The eventual system emulates five switches with alternative forwarding paths, generates real TCP/UDP traffic, measures network behavior, diagnoses four faults with local models and explanations, compares repairs in an isolated twin, and verifies assisted or policy-controlled laboratory repairs with rollback. It uses free local software and no external LLM or cloud service.

The application boundary is an unprivileged FastAPI/Streamlit process. A separately launched privileged Linux agent owns Mininet, OVS and `tc`. SQLite stores structured records; JSONL is reserved for raw events and Parquet/CSV for later datasets. Stage 3 adds validated planning under `topology` and the persistent network/traffic owner. Later work is reserved for `telemetry`, `diagnosis`, `explanations`, `twin`, `recovery` and `ui`.

## Fifteen-stage roadmap

1. Environment
2. Foundation
3. Topology and traffic
4. Faults and QoS
5. Telemetry
6. Dataset
7. Models
8. Explanations
9. Twin
10. Candidate testing and ranking
11. Repair, rollback and automation
12. Dashboard
13. Evaluation
14. Hardening
15. Final release
