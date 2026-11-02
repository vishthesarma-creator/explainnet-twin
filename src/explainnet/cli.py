"""Minimal command line lifecycle for the unprivileged service."""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import uvicorn

from explainnet.api import create_app
from explainnet.config import load_settings
from explainnet.storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="explainnet")
    parser.add_argument("--config", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "serve", "status", "stop"):
        sub.add_parser(name)
    for name in ("network-start", "network-status", "network-stop", "network-cleanup"):
        sub.add_parser(name).add_argument("instance_id")
    path_parser = sub.add_parser("path")
    path_parser.add_argument("instance_id")
    path_parser.add_argument("pair_id")
    path_parser.add_argument("path_name", choices=("primary", "alternative"))
    probe_parser = sub.add_parser("probe")
    probe_parser.add_argument("instance_id")
    probe_parser.add_argument("--source")
    probe_parser.add_argument("--target")
    traffic_parser = sub.add_parser("traffic-start")
    traffic_parser.add_argument("instance_id")
    traffic_parser.add_argument("--profiles", nargs="+", default=["critical", "bulk"])
    traffic_parser.add_argument("--duration", type=int)
    traffic_parser.add_argument("--rate-bps", type=int)
    traffic_parser.add_argument("--packet-size", type=int)
    traffic_parser.add_argument('--stream-receiver', action='store_true', default=None)
    for name in ("traffic-status", "traffic-stop"):
        run_parser = sub.add_parser(name)
        run_parser.add_argument("instance_id")
        run_parser.add_argument("run_id")
    sub.add_parser("job").add_argument("job_id")
    scenario_parser = sub.add_parser("scenario-start")
    scenario_parser.add_argument("instance_id")
    scenario_parser.add_argument("recipe_file", type=Path)
    for name in ("scenario-status", "scenario-stop", "scenario-reset"):
        sub.add_parser(name).add_argument("instance_id")
    telemetry_parser = sub.add_parser("telemetry-start")
    telemetry_parser.add_argument("instance_id")
    telemetry_parser.add_argument("--duration", type=int, default=180)
    for name in ("telemetry-stop", "telemetry-status", "telemetry-latest", "telemetry-windows", "telemetry-alerts"):
        sub.add_parser(name).add_argument("instance_id")
    sub.add_parser("telemetry-reference").add_argument("window_id")
    sub.add_parser("dataset-plan").add_argument("schedule_file", type=Path)
    for name in ("dataset-start", "dataset-status", "dataset-cancel", "dataset-resume", "dataset-export"):
        sub.add_parser(name).add_argument("batch_id")
    sub.add_parser("model-status")
    sub.add_parser("model-train").add_argument("batch_id")
    for name in ("model-load", "model-inspect"):
        sub.add_parser(name).add_argument("model_id")
    infer_parser = sub.add_parser("model-infer")
    infer_parser.add_argument("model_id")
    infer_parser.add_argument("window_id")
    infer_parser.add_argument("--mode", choices=("recorded", "live"), default="recorded")
    sub.add_parser("diagnoses").add_argument("window_id")
    explain_parser = sub.add_parser('explain')
    explain_parser.add_argument('model_id')
    explain_parser.add_argument('window_id')
    explain_parser.add_argument('--mode', choices=('recorded', 'live'), default='recorded')
    sub.add_parser('explanation').add_argument('explanation_id')
    sub.add_parser('explanation-history').add_argument('window_id')
    sub.add_parser('explanation-status')
    sub.add_parser('incidents').add_argument('--instance-id')
    sub.add_parser('incident').add_argument('incident_id')
    for command in ('lab-workflow', 'lab-apply', 'lab-mode', 'lab-undo', 'lab-automation-start'):
        sub.add_parser(command).add_argument('request_file', type=Path)
    for command in ('lab-workflow-get', 'lab-action-get', 'lab-cancel'):
        sub.add_parser(command).add_argument('record_id')
    sub.add_parser('lab-stop')
    sub.add_parser('lab-control')
    for command in ('recovery-plan', 'recovery-test'):
        sub.add_parser(command).add_argument('json_file', type=Path)
    for command in ('recovery-get', 'recovery-cancel'):
        sub.add_parser(command).add_argument('operation_id')
    snapshot_parser = sub.add_parser('twin-snapshot')
    snapshot_parser.add_argument('request_file', type=Path)
    for command in ('twin-construct', 'twin-measure', 'twin-reset', 'twin-calibrate'):
        sub.add_parser(command).add_argument('request_file', type=Path)
    for command in ('twin-status', 'twin-destroy', 'twin-cancel'):
        sub.add_parser(command).add_argument('twin_id')
    sub.add_parser('twin-snapshot-get').add_argument('snapshot_id')
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "init":
        Store(settings.database_path).initialize()
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps({"database": str(settings.database_path), "initialized": True}))
    elif args.command == "serve":
        app = create_app(settings)
        server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port))
        app.state.server = server
        server.run()
    else:
        payload = None
        method = "GET"
        if args.command in {'lab-workflow', 'lab-apply', 'lab-mode', 'lab-undo', 'lab-automation-start'}:
            suffix = {'lab-automation-start': 'automation/start'}.get(args.command, args.command[4:])
            path, method = '/v1/lab/' + suffix, 'POST'
            payload = json.loads(args.request_file.read_text(encoding='utf-8-sig'))
        elif args.command in {'lab-workflow-get', 'lab-action-get'}:
            path = '/v1/lab/' + ('workflows/' if args.command == 'lab-workflow-get' else 'actions/') + args.record_id
        elif args.command == 'lab-cancel':
            path, method, payload = '/v1/lab/cancel', 'POST', {'workflow_id': args.record_id}
        elif args.command == 'lab-stop':
            path, method = '/v1/lab/automation/stop', 'POST'
        elif args.command == 'lab-control':
            path = '/v1/lab/control'
        elif args.command in {'recovery-plan', 'recovery-test'}:
            path, method = '/v1/recovery/' + args.command[9:], 'POST'
            payload = json.loads(args.json_file.read_text(encoding='utf-8-sig'))
        elif args.command == 'recovery-get':
            path = '/v1/recovery/' + args.operation_id
        elif args.command == 'recovery-cancel':
            path, method = '/v1/recovery/cancel', 'POST'
            payload = {'operation_id': args.operation_id}
        elif args.command in {'twin-snapshot', 'twin-construct', 'twin-measure', 'twin-reset', 'twin-calibrate'}:
            path, method = '/v1/twins/' + args.command[5:], 'POST'
            payload = json.loads(args.request_file.read_text(encoding='utf-8-sig'))
        elif args.command in {'twin-destroy', 'twin-cancel'}:
            path, method = '/v1/twins/' + args.command[5:], 'POST'
            payload = {'twin_id': args.twin_id}
        elif args.command == 'twin-status':
            path = '/v1/twins/' + args.twin_id
        elif args.command == 'twin-snapshot-get':
            path = '/v1/twins/snapshots/' + args.snapshot_id
        elif args.command == "status":
            path = "/v1/health"
        elif args.command == "stop":
            path, method = "/v1/control/stop", "POST"
        elif args.command == "job":
            path = f"/v1/jobs/{args.job_id}"
        elif args.command == "network-status":
            path = f"/v1/networks/{args.instance_id}"
        elif args.command in {"network-start", "network-stop", "network-cleanup"}:
            path, method = "/v1/networks/" + args.command.split("-", 1)[1], "POST"
            payload = {"instance_id": args.instance_id}
        elif args.command == "path":
            path, method = "/v1/networks/path", "POST"
            payload = {"instance_id": args.instance_id, "pair_id": args.pair_id, "path_name": args.path_name}
        elif args.command == "probe":
            path, method = "/v1/networks/probe", "POST"
            payload = {"instance_id": args.instance_id, "source_host": args.source, "target_host": args.target}
        elif args.command == "traffic-start":
            path, method = "/v1/traffic/start", "POST"
            payload = {"instance_id": args.instance_id, "profile_ids": args.profiles, "duration_s": args.duration,
                       "offered_bps": args.rate_bps, "packet_size": args.packet_size, 'stream_receiver': args.stream_receiver}
        elif args.command == "traffic-status":
            path = f"/v1/traffic/{args.instance_id}/{args.run_id}"
        elif args.command == "scenario-status":
            path = f"/v1/laboratory/scenarios/{args.instance_id}"
        elif args.command == "dataset-plan":
            path, method = "/v1/datasets/plan", "POST"
            payload = {"schedule": json.loads(args.schedule_file.read_text(encoding="utf-8-sig"))}
        elif args.command == "model-status":
            path = "/v1/models"
        elif args.command == 'explain':
            path, method = '/v1/explanations/request', 'POST'
            payload = {'model_id': args.model_id, 'window_id': args.window_id, 'mode': args.mode}
        elif args.command == 'explanation':
            path = '/v1/explanations/' + args.explanation_id
        elif args.command == 'explanation-history':
            path = '/v1/explanations/window/' + args.window_id
        elif args.command == 'explanation-status':
            path = '/v1/explanations'
        elif args.command == 'incidents':
            path = '/v1/incidents' + ('?' + urllib.parse.urlencode({'instance_id': args.instance_id}) if args.instance_id else '')
        elif args.command == 'incident':
            path = '/v1/incidents/' + args.incident_id
        elif args.command == "model-inspect":
            path = f"/v1/models/{args.model_id}"
        elif args.command == "diagnoses":
            path = f"/v1/diagnoses/{args.window_id}"
        elif args.command in {"model-train", "model-load", "model-infer"}:
            path, method = "/v1/models/" + args.command.split("-", 1)[1], "POST"
            payload = {"batch_id": args.batch_id} if args.command == "model-train" else {"model_id": args.model_id}
            if args.command == "model-infer":
                payload.update(window_id=args.window_id, mode=args.mode)
        elif args.command == "dataset-status":
            path = f"/v1/datasets/{args.batch_id}"
        elif args.command.startswith("dataset-"):
            path, method = "/v1/datasets/" + args.command.split("-", 1)[1], "POST"
            payload = {"batch_id": args.batch_id}
        elif args.command == "telemetry-reference":
            path, method = "/v1/telemetry/reference", "POST"
            payload = {"window_id": args.window_id}
        elif args.command in {"telemetry-start", "telemetry-stop"}:
            path, method = "/v1/telemetry/" + args.command.split("-", 1)[1], "POST"
            payload = {"instance_id": args.instance_id}
            if args.command == "telemetry-start":
                payload["duration_s"] = args.duration
        elif args.command.startswith("telemetry-"):
            path = f"/v1/telemetry/{args.instance_id}/" + args.command.split("-", 1)[1]
        elif args.command.startswith("scenario-"):
            path, method = "/v1/laboratory/scenarios/" + args.command.split("-", 1)[1], "POST"
            payload = {"instance_id": args.instance_id}
            if args.command == "scenario-start":
                import yaml
                payload["scenario"] = yaml.safe_load(args.recipe_file.read_text())
        else:
            path, method = "/v1/traffic/stop", "POST"
            payload = {"instance_id": args.instance_id, "run_id": args.run_id}
        request = urllib.request.Request(f"http://{settings.host}:{settings.port}{path}",
                                         method=method, data=json.dumps(payload).encode() if payload else None,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                print(response.read().decode())
        except urllib.error.HTTPError as exc:
            parser.exit(1, exc.read().decode() + "\n")
        except urllib.error.URLError as exc:
            parser.exit(1, f"service unavailable: {exc}\n")


if __name__ == "__main__":
    main()
