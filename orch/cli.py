import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import typer
import psutil
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.markup import escape

from orch.config import load_config, find_config
from orch.manager import ProcessManager, LOG_COLORS
from orch.state import StateManager

app = typer.Typer(
    name="orch",
    help="Orch: Herramienta CLI de orquestación de procesos de desarrollo local y venvs",
    no_args_is_help=True
)

console = Console()

def get_manager(config_path: Optional[Path]) -> ProcessManager:
    """Helper to resolve config and return a ProcessManager instance."""
    try:
        cfg = load_config(config_path)
        return ProcessManager(cfg, console)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except ValueError as e:
        console.print(f"[bold red]Config Error:[/bold red] {e}")
        raise typer.Exit(code=1)

@app.command()
def up(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Ejecuta todos los servicios en primer plano (foreground), mostrando logs unificados."""
    manager = get_manager(config)
    manager.run_foreground()

@app.command()
def start(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Inicia todos los servicios en segundo plano (detached) y guarda sus PIDs."""
    manager = get_manager(config)
    success = manager.run_background()
    if not success:
        raise typer.Exit(code=1)

@app.command()
def stop(
    service: Optional[str] = typer.Argument(
        None, help="Nombre del servicio específico a detener (ej. backend). Si se omite, detiene todos."
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Detiene los servicios en ejecución en segundo plano."""
    manager = get_manager(config)
    if service:
        manager.stop_service(service)
    else:
        manager.stop_all()

@app.command()
def restart(
    service: Optional[str] = typer.Argument(
        None, help="Nombre del servicio específico a reiniciar. Si se omite, reinicia todos."
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Reinicia servicios activos en segundo plano."""
    manager = get_manager(config)
    active = manager.state_manager.get_active_services()

    # Determine services to restart
    to_restart = []
    if service:
        if service not in manager.config.services:
            console.print(f"[bold red]Error:[/bold red] Service '{service}' is not defined in config.")
            raise typer.Exit(code=1)
        to_restart.append(service)
    else:
        to_restart = list(manager.config.services.keys())

    for name in to_restart:
        # Stop if running
        if name in active:
            manager.stop_service(name)
            # Short sleep to let process release ports
            time.sleep(0.5)

        # Start again
        # Temporarily adapt run_background to start a single service
        # Let's do it inline to avoid modifying ProcessManager API
        service_config = manager.config.services[name]
        env = manager._prepare_env(service_config)
        log_path = manager.state_manager.get_log_path(name)

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n--- Service restarted at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            log_file.flush()

        log_f = open(log_path, "a", encoding="utf-8")
        console.print(f"Starting [bold cyan]{name}[/bold cyan]...")
        try:
            import subprocess
            kwargs = {
                "shell": True,
                "cwd": str(service_config.path),
                "env": env,
                "stdout": log_f,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                # CREATE_NEW_CONSOLE (0x10) | CREATE_NO_WINDOW (0x08000000) | CREATE_BREAKAWAY_FROM_JOB (0x01000000)
                kwargs["creationflags"] = 0x00000010 | 0x08000000 | 0x01000000
            else:
                kwargs["start_new_session"] = True

            proc = subprocess.Popen(service_config.command, **kwargs)
            ps_proc = psutil.Process(proc.pid)
            create_time = ps_proc.create_time()

            manager.state_manager.update_service(name, proc.pid, service_config.command, create_time)
            console.print(f"  * [bold green]{name}[/bold green] restarted with PID {proc.pid}")
        except Exception as e:
            console.print(f"  x [bold red]{name}[/bold red] failed to start: {e}")
        finally:
            log_f.close()

def format_uptime(seconds: float) -> str:
    """Format seconds into hh:mm:ss."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

@app.command()
def status(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Muestra el estado de los servicios en segundo plano y su consumo de recursos."""
    manager = get_manager(config)
    # This updates stale services in state.json to CRASHED
    active = manager.state_manager.get_active_services()
    state = manager.state_manager.load_state()
    services_state = state.get("services", {})

    table = Table(title=f"Project: {manager.config.project_name} (Services Status)")
    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("PID", style="magenta", justify="center")
    table.add_column("CPU %", justify="right")
    table.add_column("Memory (MB)", justify="right")
    table.add_column("Uptime", justify="center")

    # In order to measure CPU percent properly on psutil, we should initialize it once,
    # sleep briefly, and fetch again. We'll do a quick 0.1s check.
    proc_objs = {}
    for name, info in active.items():
        pid = info["pid"]
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)
            proc_objs[name] = proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    time.sleep(0.1) # Brief sleep to get meaningful CPU readings

    for name in manager.config.services.keys():
        svc_state = services_state.get(name, {})
        status_val = svc_state.get("status", "STOPPED")

        if name in active and name in proc_objs:
            proc = proc_objs[name]
            try:
                cpu = proc.cpu_percent(interval=None)
                # Sum CPU of children processes as well (common for npm/sub-shells)
                for child in proc.children(recursive=True):
                    try:
                        cpu += child.cpu_percent(interval=None)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                mem_bytes = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        mem_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                mem_mb = mem_bytes / (1024 * 1024)
                uptime = time.time() - proc.create_time()

                table.add_row(
                    name,
                    "[bold green]RUNNING[/bold green]",
                    str(proc.pid),
                    f"{cpu:.1f}%",
                    f"{mem_mb:.1f} MB",
                    format_uptime(uptime)
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                table.add_row(name, "[bold red]CRASHED[/bold red]", str(svc_state.get("pid", "-")), "0.0%", "0.0 MB", "00:00:00")
        elif status_val == "CRASHED":
            table.add_row(
                name,
                "[bold red]CRASHED[/bold red]",
                str(svc_state.get("pid", "-")),
                "0.0%",
                "0.0 MB",
                "00:00:00"
            )
        else:
            table.add_row(
                name,
                "[bold yellow]STOPPED[/bold yellow]",
                "-",
                "-",
                "-",
                "-"
            )

    console.print(table)

def tail_file(filepath: Path, console: Console, prefix: str, color: str, stop_event: Any, lines_back: int = 50):
    """Tail a single log file in a blocking thread."""
    if not filepath.exists():
        console.print(f"\\\\[[{color}]{prefix}[/{color}]] [yellow]Waiting for log file to be created...[/yellow]")
        while not filepath.exists() and not stop_event.is_set():
            time.sleep(0.5)

    if stop_event.is_set():
        return

    # Read last lines_back lines
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        # Simple tail implementation
        content = f.readlines()
        last_lines = content[-lines_back:]
        for line in last_lines:
            clean_line = line.rstrip(chr(10)).rstrip(chr(13))
            console.print(f"\\\\[[{color}]{prefix}[/{color}]] {escape(clean_line)}")

        # Seek to end and tail
        f.seek(0, os.SEEK_END)
        while not stop_event.is_set():
            line = f.readline()
            if line:
                clean_line = line.rstrip(chr(10)).rstrip(chr(13))
                console.print(f"\\\\[[{color}]{prefix}[/{color}]] {escape(clean_line)}")
            else:
                time.sleep(0.1)

@app.command()
def logs(
    service: Optional[str] = typer.Argument(
        None, help="Nombre del servicio específico a consultar. Si se omite, muestra de todos."
    ),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Seguir los logs en tiempo real (tail -f)"
    ),
    lines: int = typer.Option(
        50, "--lines", "-n", help="Número de líneas del historial a mostrar"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Muestra y sigue los logs de los servicios en segundo plano."""
    manager = get_manager(config)
    active = manager.state_manager.get_active_services()

    services_to_show = []
    if service:
        if service not in manager.config.services:
            console.print(f"[bold red]Error:[/bold red] Service '{service}' is not defined in config.")
            raise typer.Exit(code=1)
        services_to_show.append(service)
    else:
        services_to_show = list(manager.config.services.keys())

    if not follow:
        # Just display the last N lines
        for name in services_to_show:
            log_path = manager.state_manager.get_log_path(name)
            console.print(f"\n--- [bold cyan]Logs for {name}[/bold cyan] ({log_path.name}) ---")
            if not log_path.exists():
                console.print("[yellow]No logs recorded yet.[/yellow]")
                continue
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines_list = f.readlines()
                for line in lines_list[-lines:]:
                    print(line.rstrip("\r\n"))
    else:
        # Multi-file follow
        import threading
        stop_event = threading.Event()
        threads = []

        console.print("[bold green]Following logs in real-time. Press Ctrl+C to stop...[/bold green]\n")
        try:
            for idx, name in enumerate(services_to_show):
                color = LOG_COLORS[idx % len(LOG_COLORS)]
                log_path = manager.state_manager.get_log_path(name)
                t = threading.Thread(
                    target=tail_file,
                    args=(log_path, console, name, color, stop_event, lines),
                    daemon=True
                )
                t.start()
                threads.append(t)

            # Wait loop until interrupted
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Stopping log follower...[/bold yellow]")
        finally:
            stop_event.set()
            for t in threads:
                t.join(timeout=1.0)

@app.command()
def clean(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Ruta al archivo orch.yml / project.yml"
    )
):
    """Detiene los servicios activos, vacía los logs y limpia el archivo de estado."""
    manager = get_manager(config)
    
    # 1. Stop background services if running
    active = manager.state_manager.get_active_services()
    if active:
        console.print("[bold yellow]Deteniendo servicios activos antes de limpiar...[/bold yellow]")
        manager.stop_all()
        # Sleep briefly to ensure process cleanup
        time.sleep(1.0)
        
    # 2. Clean logs
    logs_dir = manager.state_manager.logs_dir
    if logs_dir.exists():
        console.print("[bold blue]Limpiando archivos de logs...[/bold blue]")
        for log_file in logs_dir.glob("*.log"):
            try:
                # Open in write-mode and close to truncate to 0 bytes
                with open(log_file, "w", encoding="utf-8") as f:
                    pass
                console.print(f"  * Log {log_file.name} vaciado.")
            except Exception as e:
                console.print(f"  x No se pudo vaciar {log_file.name}: {e}")
                
    # 3. Clean state file
    state_file = manager.state_manager.state_file
    if state_file.exists():
        console.print("[bold blue]Reseteando archivo de estado...[/bold blue]")
        try:
            manager.state_manager.save_state({"services": {}})
            console.print("  * Estado reseteado.")
        except Exception as e:
            console.print(f"  x No se pudo resetear el estado: {e}")
            
    console.print("[bold green]Limpieza completada con éxito.[/bold green]")

if __name__ == "__main__":
    app()
