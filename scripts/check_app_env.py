#!/usr/bin/env python3
"""Check Stage 1 application imports using the dedicated Linux venv."""

import importlib
import importlib.metadata
import json
import sys
from pathlib import Path

PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scikit-learn": "sklearn",
    "shap": "shap",
    "networkx": "networkx",
    "fastapi": "fastapi",
    "streamlit": "streamlit",
    "plotly": "plotly",
    "pydantic": "pydantic",
    "PyYAML": "yaml",
    "joblib": "joblib",
    "psutil": "psutil",
    "pyarrow": "pyarrow",
    "pytest": "pytest",
    "ruff": "ruff",
    "uvicorn": "uvicorn",
}

result = {"python": sys.version.split()[0], "packages": {}, "errors": []}
for distribution, module in PACKAGES.items():
    try:
        importlib.import_module(module)
        result["packages"][distribution] = importlib.metadata.version(distribution)
    except Exception as exc:  # noqa: BLE001 - report every import failure
        result["errors"].append(f"{distribution}: {type(exc).__name__}: {exc}")
try:
    importlib.import_module("mininet")
    result["venv_imports_os_mininet"] = True
except ModuleNotFoundError:
    result["venv_imports_os_mininet"] = False

output = Path(__file__).resolve().parents[1] / "artifacts" / "application_imports.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(bool(result["errors"]))
