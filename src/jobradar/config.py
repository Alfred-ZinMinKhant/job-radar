from pathlib import Path

import yaml
from dotenv import load_dotenv


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: str | Path = "config.yaml") -> dict:
    """Load config.yaml, merge optional config.local.yaml over it, load .env."""
    path = Path(path).resolve()
    root = path.parent
    load_dotenv(root / ".env")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    local = root / "config.local.yaml"
    if local.exists():
        cfg = _merge(cfg, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    cfg["_root"] = str(root)
    return cfg
