import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
import psutil

class StateManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.orch_dir = self.base_dir / ".orch"
        self.state_file = self.orch_dir / "state.json"
        self.logs_dir = self.orch_dir / "logs"

    def ensure_dirs(self):
        """Ensure .orch and .orch/logs directories exist."""
        self.orch_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> Dict[str, Any]:
        """Load state JSON, returning empty dict if not existing or invalid."""
        if not self.state_file.exists():
            return {"services": {}}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"services": {}}

    def save_state(self, state: Dict[str, Any]):
        """Save state dict to state.json."""
        self.ensure_dirs()
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def update_service(self, name: str, pid: int, command: str, create_time: float):
        """Update or insert a running service entry."""
        state = self.load_state()
        state["services"][name] = {
            "pid": pid,
            "command": command,
            "started_at": time.time(),
            "create_time": create_time,
            "log_file": str(self.get_log_path(name)),
            "status": "RUNNING",
        }
        self.save_state(state)

    def remove_service(self, name: str):
        """Mark a service entry as STOPPED cleanly."""
        state = self.load_state()
        if name in state["services"]:
            state["services"][name]["status"] = "STOPPED"
            state["services"][name]["pid"] = None
            state["services"][name]["create_time"] = None
        else:
            state["services"][name] = {
                "pid": None,
                "command": "",
                "started_at": None,
                "create_time": None,
                "log_file": str(self.get_log_path(name)),
                "status": "STOPPED",
            }
        self.save_state(state)

    def get_log_path(self, name: str) -> Path:
        """Get the absolute path to a service's log file."""
        self.ensure_dirs()
        return (self.logs_dir / f"{name}.log").resolve()

    def get_active_services(self) -> Dict[str, Dict[str, Any]]:
        """
        Verify PIDs against OS processes. Returns active services only.
        Updates stale entries to 'CRASHED' in the state file.
        """
        state = self.load_state()
        services = state.get("services", {})
        active = {}
        changed = False

        for name, info in list(services.items()):
            if info.get("status") == "STOPPED":
                continue

            pid = info.get("pid")
            saved_create_time = info.get("create_time")

            is_alive = False
            if pid and psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    # Check if create_time matches within a reasonable delta
                    proc_create_time = proc.create_time()
                    if saved_create_time and abs(proc_create_time - saved_create_time) < 1.5:
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            is_alive = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if is_alive:
                active[name] = info
                if info.get("status") != "RUNNING":
                    info["status"] = "RUNNING"
                    changed = True
            else:
                # Process is dead, but was not stopped cleanly -> CRASHED
                if info.get("status") != "CRASHED":
                    info["status"] = "CRASHED"
                    changed = True

        if changed:
            self.save_state(state)

        return active
