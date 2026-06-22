import pytest
from pathlib import Path
from orch.config import load_config, find_config, ProjectConfig, ServiceConfig

def test_service_config_valid():
    base_dir = Path("/tmp")
    data = {
        "path": "./app",
        "command": "python app.py",
        "env": {"DEBUG": "true"},
        "restart": "always"
    }
    svc = ServiceConfig("backend", data, base_dir)
    assert svc.name == "backend"
    assert svc.command == "python app.py"
    assert svc.env == {"DEBUG": "true"}
    assert svc.restart == "always"
    assert svc.path == base_dir / "app"

def test_service_config_missing_command():
    base_dir = Path("/tmp")
    data = {"path": "./app"}
    with pytest.raises(ValueError, match="must have a 'command' specified"):
        ServiceConfig("backend", data, base_dir)

def test_project_config_valid(tmp_path):
    config_content = """
project: test-project
env:
  type: venv
  path: ./my-venv
  variables:
    GLOBAL_VAR: "hello"
services:
  api:
    path: ./api
    command: python api.py
"""
    config_file = tmp_path / "orch.yml"
    config_file.write_text(config_content, encoding="utf-8")

    cfg = ProjectConfig(config_file)
    assert cfg.project_name == "test-project"
    assert cfg.env_type == "venv"
    assert cfg.env_path == (tmp_path / "my-venv").resolve()
    assert cfg.global_vars == {"GLOBAL_VAR": "hello"}
    assert "api" in cfg.services
    assert cfg.services["api"].command == "python api.py"

def test_project_config_missing_project(tmp_path):
    config_content = """
services:
  api:
    command: python api.py
"""
    config_file = tmp_path / "orch.yml"
    config_file.write_text(config_content, encoding="utf-8")
    with pytest.raises(ValueError, match="must specify a 'project' name"):
        ProjectConfig(config_file)

def test_project_config_missing_services(tmp_path):
    config_content = """
project: test-project
"""
    config_file = tmp_path / "orch.yml"
    config_file.write_text(config_content, encoding="utf-8")
    with pytest.raises(ValueError, match="must define at least one service"):
        ProjectConfig(config_file)

def test_find_config_success(tmp_path):
    config_file = tmp_path / "project.yaml"
    config_file.touch()
    
    # search path is tmp_path
    found = find_config(tmp_path)
    assert found == config_file

def test_find_config_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Could not find"):
        find_config(tmp_path)
