from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "harness_policy.yaml"


def load_harness_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else _DEFAULT_PATH
    try:
        with policy_path.open(encoding="utf-8") as policy_file:
            policy = yaml.safe_load(policy_file)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load harness policy: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise ValueError("Harness policy must be a version 1 YAML object.")
    return policy
