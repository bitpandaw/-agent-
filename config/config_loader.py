import yaml
from pathlib import Path
def read_config():
    config_path = Path(__file__).resolve().parent/ "config.yaml"
    try:
        with config_path.open(mode="r",encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
        return config_dict
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML format in {config_path}: {e}")
    except OSError as e:
        raise OSError(f"Failed to read config file {config_path}: {e}")
config = read_config()