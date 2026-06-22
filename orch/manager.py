import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import psutil
from rich.console import Console
from rich.markup import escape

from orch.config import ProjectConfig, ServiceConfig
from orch.state import StateManager

# Colors for service logs
LOG_COLORS = ["cyan", "magenta", "green", "yellow", "blue", "bright_red", "bright_green", "bright_yellow", "bright_blue", "bright_magenta", "bright_cyan"]

class ProcessManager:
    def __init__(self, config: ProjectConfig, console: Console):
        self.config = config
        self.console = console
        self.state_manager = StateManager(config.base_dir)
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()

    def _prepare_env(self, service: ServiceConfig) -> Dict[str, str]:
        """Merge system env, global env variables, service env variables and inject venv if active."""
        env = os.environ.copy()

        # Inject global variables
        for k, v in self.config.global_vars.items():
            env[k] = str(v)

        # Inject service-specific variables
        for k, v in service.env.items():
            env[k] = str(v)

        # Inject virtual environment if configured
        if self.config.env_type == "venv" and self.config.env_path:
            venv_path = self.config.env_path
            
            # Determine path to venv binary/scripts directory
            if sys.platform == "win32":
                bin_dir = venv_path / "Scripts"
            else:
                bin_dir = venv_path / "bin"

            if bin_dir.exists():
                # Prepend venv's bin to PATH
                env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
                env["VIRTUAL_ENV"] = str(venv_path)
                # Remove PYTHONHOME if set to prevent issues with virtual envs
                env.pop("PYTHONHOME", None)
            else:
                self.console.print(f"[yellow]Warning: Virtualenv path '{venv_path}' is configured, but '{bin_dir}' was not found.[/yellow]")

        return env

    def _read_stream(self, name: str, stream: Any, color: str):
        """Read line by line from stream and print to console with colored prefix."""
        while not self._stop_event.is_set():
            line = stream.readline()
            if not line:
                break
            # Decode and strip line breaks
            decoded = line.rstrip("\r\n")
            self.console.print(f"\\[[{color}]{name}[/{color}]] {escape(decoded)}")

    def run_foreground(self):
        """Run all services in foreground mode, multiplexing logs to stdout."""
        self.console.print(f"[bold green]Starting project '{self.config.project_name}' in foreground mode...[/bold green]")
        self.console.print("Press [bold red]Ctrl+C[/bold red] to stop all services.\n")

        # Check if services are already running in background
        active_background = self.state_manager.get_active_services()
        if active_background:
            self.console.print("[yellow]Warning: Some services are already running in the background. Running in foreground might cause port conflicts.[/yellow]")

        services = list(self.config.services.values())
        
        try:
            for idx, service in enumerate(services):
                color = LOG_COLORS[idx % len(LOG_COLORS)]
                env = self._prepare_env(service)

                self.console.print(f"[bold blue]Starting service '{service.name}'...[/bold blue]")
                
                # On Windows, using shell=True allows running npm/python command strings naturally
                # We merge stderr into stdout for combined streaming
                proc = subprocess.Popen(
                    service.command,
                    shell=True,
                    cwd=str(service.path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1 # Line buffered
                )

                self.active_processes[service.name] = proc

                # Start a thread to read output
                t = threading.Thread(
                    target=self._read_stream,
                    args=(service.name, proc.stdout, color),
                    daemon=True
                )
                t.start()
                self._threads.append(t)

            # Wait loop to monitor processes
            while self.active_processes:
                dead_services = []
                for name, proc in list(self.active_processes.items()):
                    ret = proc.poll()
                    if ret is not None:
                        self.console.print(f"[bold red][{name}] Process exited with code {ret}[/bold red]")
                        dead_services.append(name)
                
                for name in dead_services:
                    del self.active_processes[name]
                
                time.sleep(0.5)

        except KeyboardInterrupt:
            self.console.print("\n[bold yellow]Stopping all services...[/bold yellow]")
        finally:
            self.stop_all(foreground=True)

    def run_background(self) -> bool:
        """Start all services in detached background mode, writing logs to files."""
        self.state_manager.ensure_dirs()
        active = self.state_manager.get_active_services()
        
        success = True
        for name, service in self.config.services.items():
            if name in active:
                self.console.print(f"[yellow]Service '{name}' is already running (PID: {active[name]['pid']}). Skipping...[/yellow]")
                continue

            env = self._prepare_env(service)
            log_path = self.state_manager.get_log_path(name)
            
            # Open log file in append mode, write run header
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"\n--- Service started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                log_file.flush()

            # Open log file for sub-process stdout/stderr redirection
            # We open in write mode (to append, we pass file handles)
            log_f = open(log_path, "a", encoding="utf-8")

            self.console.print(f"Starting [bold cyan]{name}[/bold cyan]...")
            try:
                # We need to spawn process detached so it survives parent exiting
                # On Windows, we can use CREATE_NEW_PROCESS_GROUP
                # On Unix, we can use start_new_session=True (or preexec_fn=os.setsid)
                # stdout and stderr go directly to log file, stdin is DEVNULL
                kwargs = {
                    "shell": True,
                    "cwd": str(service.path),
                    "env": env,
                    "stdout": log_f,
                    "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL,
                }
                
                if sys.platform == "win32":
                    # CREATE_NEW_PROCESS_GROUP (0x200) | CREATE_BREAKAWAY_FROM_JOB (0x01000000)
                    kwargs["creationflags"] = 0x00000200 | 0x01000000
                else:
                    kwargs["start_new_session"] = True

                proc = subprocess.Popen(service.command, **kwargs)
                
                # Fetch create_time using psutil to prevent PID recycle issue
                ps_proc = psutil.Process(proc.pid)
                create_time = ps_proc.create_time()

                self.state_manager.update_service(name, proc.pid, service.command, create_time)
                self.console.print(f"  * [bold green]{name}[/bold green] started with PID {proc.pid}")
            except Exception as e:
                self.console.print(f"  x [bold red]{name}[/bold red] failed to start: {e}")
                success = False
            finally:
                log_f.close()

        return success

    def stop_all(self, foreground: bool = False):
        """Stop all processes. If foreground, stops active_processes. If background, reads state file."""
        self._stop_event.set()
        
        if foreground:
            for name, proc in list(self.active_processes.items()):
                self.console.print(f"Stopping [bold yellow]{name}[/bold yellow] (PID {proc.pid})...")
                self.kill_process_tree(proc.pid)
            self.active_processes.clear()
        else:
            state = self.state_manager.load_state()
            services = state.get("services", {})
            
            stopped_any = False
            for name, info in services.items():
                if info.get("status") == "STOPPED":
                    continue
                
                pid = info.get("pid")
                if pid:
                    self.console.print(f"Stopping [bold yellow]{name}[/bold yellow] (PID {pid})...")
                    self.kill_process_tree(pid)
                else:
                    self.console.print(f"Clearing stale state for [bold yellow]{name}[/bold yellow]...")
                
                self.state_manager.remove_service(name)
                stopped_any = True
            
            if stopped_any:
                self.console.print("[bold green]All services stopped/cleared.[/bold green]")
            else:
                self.console.print("[yellow]No active or crashed services found to stop.[/yellow]")

    def stop_service(self, name: str):
        """Stop a specific background service."""
        state = self.state_manager.load_state()
        services = state.get("services", {})
        if name not in services or services[name].get("status") == "STOPPED":
            self.console.print(f"[yellow]Service '{name}' is not running in the background.[/yellow]")
            return

        info = services[name]
        pid = info.get("pid")
        if pid:
            self.console.print(f"Stopping [bold yellow]{name}[/bold yellow] (PID {pid})...")
            self.kill_process_tree(pid)
        
        self.state_manager.remove_service(name)
        self.console.print(f"[bold green]Service '{name}' stopped.[/bold green]")

    def kill_process_tree(self, pid: int):
        """Recursively terminate parent PID and all its child processes."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # Send terminate signal to children first
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # Terminate parent
            parent.terminate()

            # Wait up to 2 seconds for clean termination
            gone, alive = psutil.wait_procs(children + [parent], timeout=2.0)
            
            # Force kill survivors
            for survivor in alive:
                try:
                    self.console.print(f"  [red]Force killing survivor process PID {survivor.pid}[/red]")
                    survivor.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            self.console.print(f"[red]Error killing process tree for PID {pid}: {e}[/red]")
