import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigLoader:
    """
    A utility to load configuration from YAML files and environment variables.

    The loader follows a specific hierarchy for loading configurations:
    1. A base configuration file (`base.yaml`).
    2. An environment-specific configuration file (e.g., `development.yaml`).
    3. Environment variables (prefixed with a given prefix, e.g., `APP_`).

    Settings from later sources override earlier ones.
    """

    def __init__(self, config_dir: Path, env_prefix: str = "APP"):
        """
        Initializes the ConfigLoader.

        Args:
            config_dir: The directory where configuration files are located.
            env_prefix: The prefix for environment variables to be loaded.
        """
        if not config_dir.is_dir():
            raise FileNotFoundError(f"Configuration directory not found: {config_dir}")
        self.config_dir = config_dir
        self.env_prefix = f"{env_prefix}_"

    def load(self, env: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads the configuration based on the environment.

        Args:
            env: The environment to load. If None, it defaults to the value of
                 the `APP_ENV` environment variable, or 'development'.

        Returns:
            A dictionary containing the final merged configuration.
        """
        if env is None:
            env = os.environ.get("APP_ENV", "development")

        # 1. Load base configuration
        base_config = self._load_yaml_file(self.config_dir / "base.yaml")

        # 2. Load environment-specific configuration and merge
        env_config_path = self.config_dir / f"{env}.yaml"
        env_config = self._load_yaml_file(env_config_path)
        merged_config = self._deep_merge(base_config, env_config)

        # 3. Load from environment variables and merge
        env_vars_config = self._load_from_env()
        final_config = self._deep_merge(merged_config, env_vars_config)

        return final_config

    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """Loads a YAML file if it exists, otherwise returns an empty dict."""
        if not file_path.is_file():
            return {}
        with open(file_path, "r") as f:
            try:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
            except yaml.YAMLError:
                return {}

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Recursively merges two dictionaries."""
        merged = base.copy()
        for key, value in override.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _load_from_env(self) -> Dict[str, Any]:
        """Loads and parses configuration from environment variables."""
        config = {}
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                # Remove prefix and split by double underscore for nesting
                path = key[len(self.env_prefix):].lower().split("__")
                
                parsed_value = self._parse_value(value)

                d = config
                for part in path[:-1]:
                    if part not in d:
                        d[part] = {}
                    d = d[part]
                d[path[-1]] = parsed_value
        return config

    def _parse_value(self, value: str) -> Any:
        """Attempts to convert string value to int, float, or bool."""
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
