import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from orch.state import StateManager

def test_state_manager_init(tmp_path):
    mgr = StateManager(tmp_path)
    assert mgr.base_dir == tmp_path.resolve()
    assert mgr.orch_dir == tmp_path / ".orch"
    assert mgr.state_file == tmp_path / ".orch" / "state.json"
    assert mgr.logs_dir == tmp_path / ".orch" / "logs"

def test_ensure_dirs(tmp_path):
    mgr = StateManager(tmp_path)
    assert not mgr.orch_dir.exists()
    assert not mgr.logs_dir.exists()
    
    mgr.ensure_dirs()
    assert mgr.orch_dir.exists()
    assert mgr.logs_dir.exists()

def test_load_state_empty(tmp_path):
    mgr = StateManager(tmp_path)
    state = mgr.load_state()
    assert state == {"services": {}}

def test_save_and_load_state(tmp_path):
    mgr = StateManager(tmp_path)
    test_state = {"services": {"backend": {"pid": 1234, "status": "RUNNING"}}}
    mgr.save_state(test_state)
    
    loaded = mgr.load_state()
    assert loaded == test_state

def test_update_and_remove_service(tmp_path):
    mgr = StateManager(tmp_path)
    mgr.update_service("backend", 1234, "python app.py", 1000.0)
    
    state = mgr.load_state()
    assert "backend" in state["services"]
    assert state["services"]["backend"]["pid"] == 1234
    assert state["services"]["backend"]["command"] == "python app.py"
    assert state["services"]["backend"]["create_time"] == 1000.0
    assert state["services"]["backend"]["status"] == "RUNNING"
    
    # Remove service should transition status to STOPPED
    mgr.remove_service("backend")
    state_after = mgr.load_state()
    assert state_after["services"]["backend"]["status"] == "STOPPED"
    assert state_after["services"]["backend"]["pid"] is None

@patch("psutil.pid_exists")
@patch("psutil.Process")
def test_get_active_services(mock_process_class, mock_pid_exists, tmp_path):
    mgr = StateManager(tmp_path)
    
    # Pre-populate state
    test_state = {
        "services": {
            "backend": {
                "pid": 1234,
                "command": "python app.py",
                "create_time": 1000.0,
                "status": "RUNNING"
            },
            "frontend": {
                "pid": 5678,
                "command": "npm start",
                "create_time": 2000.0,
                "status": "RUNNING"
            }
        }
    }
    mgr.save_state(test_state)
    
    # Mocking behavior:
    # 1. PID 1234 is alive and matches create_time
    # 2. PID 5678 is dead (e.g., pid_exists returns False)
    
    def side_effect_pid_exists(pid):
        return pid == 1234
        
    mock_pid_exists.side_effect = side_effect_pid_exists
    
    # Mock Process for PID 1234
    mock_proc = MagicMock()
    mock_proc.create_time.return_value = 1000.0
    mock_proc.is_running.return_value = True
    mock_proc.status.return_value = "running"
    mock_process_class.return_value = mock_proc
    
    active = mgr.get_active_services()
    
    # Check return value
    assert "backend" in active
    assert "frontend" not in active
    
    # Check saved file status: frontend should be marked as CRASHED because it was running but process is gone
    updated_state = mgr.load_state()
    assert updated_state["services"]["backend"]["status"] == "RUNNING"
    assert updated_state["services"]["frontend"]["status"] == "CRASHED"
