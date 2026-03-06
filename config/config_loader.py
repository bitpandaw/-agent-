from pathlib import Path
from typing import Any

import yaml


def read_config() -> dict[str, Any]:
    config_path: Path = Path(__file__).resolve().parent / "config.yaml"
    try:
        with config_path.open(mode="r", encoding="utf-8") as f:
            config_dict: dict[str, Any] | None = yaml.safe_load(f)
        return config_dict if isinstance(config_dict, dict) else {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format in {config_path}: {e}")
    except OSError as e:
        raise OSError(f"Failed to read config file {config_path}: {e}") from e


config = read_config()