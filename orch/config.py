import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml

class ServiceConfig:
    def __init__(self, name: str, data: Dict[str, Any], base_dir: Path):
        self.name = name
        self.path = base_dir / Path(data.get("path", "."))
        self.command = data.get("command")
        self.env = data.get("env", {})
        self.restart = data.get("restart", "no") # 'no', 'always', 'on-failure'

        if not self.command:
            raise ValueError(f"Service '{name}' must have a 'command' specified.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "command": self.command,
            "env": self.env,
            "restart": self.restart,
        }

class ProjectConfig:
    def __init__(self, filepath: Path):
        self.filepath = filepath.resolve()
        self.base_dir = self.filepath.parent
        
        with open(self.filepath, "r", encoding="utf-8") as f:
            try:
                self.data = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML file: {e}")

        self.project_name = self.data.get("project")
        if not self.project_name:
            raise ValueError("Config must specify a 'project' name.")

        # Parse global environment config
        env_data = self.data.get("env", {})
        self.env_type = env_data.get("type")
        self.env_path = None
        if env_data.get("path"):
            self.env_path = (self.base_dir / Path(env_data["path"])).resolve()
        self.global_vars = env_data.get("variables", {})

        # Parse services
        services_data = self.data.get("services", {})
        if not services_data:
            raise ValueError("Config must define at least one service.")
            
        self.services: Dict[str, ServiceConfig] = {}
        for name, svc_data in services_data.items():
            self.services[name] = ServiceConfig(name, svc_data, self.base_dir)

def find_config(search_path: Optional[Path] = None) -> Path:
    """
    Search for a default configuration file starting from search_path and walking up.
    """
    candidates = ["orch.yml", "orch.yaml", "project.yml", "project.yaml"]
    current = Path(search_path or os.getcwd()).resolve()

    # Search upwards
    for parent in [current] + list(current.parents):
        for candidate in candidates:
            path = parent / candidate
            if path.exists() and path.is_file():
                return path

    raise FileNotFoundError(
        "Could not find orch.yml, orch.yaml, project.yml, or project.yaml in this directory or any parent directories."
    )

def load_config(filepath: Optional[Path] = None) -> ProjectConfig:
    if filepath is None:
        filepath = find_config()
    else:
        filepath = Path(filepath).resolve()
        if not filepath.exists():
            raise FileNotFoundError(f"Configuration file not found: {filepath}")
    
    return ProjectConfig(filepath)
