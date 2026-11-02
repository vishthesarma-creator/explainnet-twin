"""Re-export structural audits from measured persisted evidence; no fitting or plotting."""

import argparse
import json
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import export_dataset
from explainnet.storage import Store

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--batch-id", required=True)
args = parser.parse_args()
settings = load_settings(args.config)
result = export_dataset(Store(settings.database_path), args.batch_id)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["quality"]["structural_checks_passed"] else 1)
