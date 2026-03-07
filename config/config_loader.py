"""配置加载模块：从 config.yaml 读取配置。"""

from pathlib import Path
from typing import Any

import yaml


def read_config() -> dict[str, Any]:
    """读取并解析配置文件。

    :return: 配置字典
    :raises FileNotFoundError: 配置文件不存在
    :raises ValueError: YAML 格式错误
    :raises OSError: 文件读取失败
    """
    config_path: Path = Path(__file__).resolve().parent / "config.yaml"
    try:
        with config_path.open(mode="r", encoding="utf-8") as f:
            config_dict: dict[str, Any] | None = yaml.safe_load(f)
        return config_dict if isinstance(config_dict, dict) else {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}") from None
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format in {config_path}: {e}") from e
    except OSError as e:
        raise OSError(f"Failed to read config file {config_path}: {e}") from e


config: dict[str, Any] = read_config()