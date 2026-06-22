# Orch - Local Service Orchestrator

[![PyPI version](https://img.shields.io/pypi/v/orch-cli.svg)](https://pypi.org/project/orch-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://github.com/EASYLIFECODE/orch-cli/workflows/CI/badge.svg)](https://github.com/EASYLIFECODE/orch-cli/actions)

**Orch** is a lightweight, **daemon-less** command-line interface (CLI) tool designed to simplify local development of client-server or multi-service architectures. 

It runs your scripts, servers, frontends, and workers concurrently, manages their Python virtual environments (`venv`) transparently, monitors their resources, and multiplexes their logs—**without** the overhead of Docker or background daemon processes.

---

## Key Features

- 🔌 **Daemon-less Architecture**: No persistent background services needed. State is safely tracked locally in `.orch/state.json`.
- 🐍 **Automatic venv Detection**: Injects your project's Python virtual environment (`venv`) to the process execution path automatically—no manual activation scripts required.
- 🎨 **Unified Multiplexed Logs**: Streams output from all services into a single terminal window with distinct, customizable color prefixes, protecting ANSI markup.
- 🌙 **Background Execution**: Spawn services in detached modes, persisting output to individual log files.
- 📊 **Resource Monitoring**: Track CPU, Memory consumption, and uptime per service with a single command.
- 🛡️ **Clean Process Tree Teardown**: Intercepts shutdown signals and recursively kills child processes (e.g. Node sub-processes, shell scripts) cleanly, avoiding orphaned processes.
- 🛡️ **PID Recycle Protection**: Safeguards against re-using recycled PIDs by validating the OS process creation time before killing or reporting status.

---

## Installation

### Stable Release (via PyPI)

```bash
pip install orch-cli
```

### From Source (Development Mode)

1. Clone the repository:
   ```bash
   git clone https://github.com/EASYLIFECODE/orch-cli.git
   cd orch-cli
   ```

2. Install in editable development mode:
   ```bash
   pip install -e .
   ```

---

## Configuration (`orch.yml`)

Configure your services in an `orch.yml` or `project.yml` file in the root of your project:

```yaml
# orch.yml
project: my-awesome-app

# Global environment configuration
env:
  type: venv               # Type of virtual environment
  path: ./venv            # Path to the virtualenv folder
  variables:
    GLOBAL_VAR: "shared-value"
    DATABASE_URL: "sqlite:///local.db"

services:
  backend:
    path: ./backend        # Working directory for this service
    command: python app.py  # Automatically runs using the configured global venv
    env:
      PORT: "8000"

  frontend:
    path: ./frontend
    command: npm run dev
    env:
      VITE_API_URL: "http://localhost:8000"

  worker:
    path: ./worker
    command: python worker.py
```

---

## CLI Usage

### 1. Run in Foreground (Interactive Mode)

Launches all services concurrently, streaming their colored logs into the active console. Pressing `Ctrl+C` cleanly shuts down all services.

```bash
orch up
```

### 2. Run in Background (Detached Mode)

Launches all services in the background and saves their state.

```bash
orch start
```

### 3. Check Service Status & Resource Usage

Displays an elegant table showing running status, PID, CPU, Memory usage (recursive of all child processes), and uptime.

```bash
orch status
```

*Example Output:*
```text
           Project: my-awesome-app (Services Status)
┌──────────┬─────────┬───────┬───────┬─────────────┬──────────┐
│ Service  │ Status  │  PID  │ CPU % │ Memory (MB) │  Uptime  │
├──────────┼─────────┼───────┼───────┼─────────────┼──────────┤
│ backend  │ RUNNING │ 12452 │  0.2% │     45.4 MB │ 00:12:30 │
│ frontend │ RUNNING │ 12459 │  0.0% │     82.1 MB │ 00:12:30 │
│ worker   │ RUNNING │ 12461 │  1.5% │     32.7 MB │ 00:12:28 │
└──────────┴─────────┴───────┴───────┴─────────────┴──────────┘
```

### 4. Consult and Tail Logs

Tail log files of services running in the background.

```bash
# Follow logs of all services
orch logs -f

# Follow logs of a specific service
orch logs backend -f

# Read last 100 lines without following
orch logs frontend --lines 100
```

### 5. Restart Services

Restarts all or specific services running in the background.

```bash
# Restart all
orch restart

# Restart only backend
orch restart backend
```

### 6. Stop Services

Stops services running in the background and cleans up state.

```bash
# Stop all services
orch stop

# Stop a specific service
orch stop backend
```

### 7. Clean State & Logs

Terminates background services, clears log files (`.orch/logs/*.log`) to 0 bytes, and resets the state file.

```bash
orch clean
```

---

## Technical Architecture

Orch is built using **Python 3.8+**, **Typer** for the CLI framework, **Rich** for visual output rendering, and **psutil** for platform-independent process controls.

```text
                     [ CLI Command: orch ]
                              │
                    [ Load Configuration ]
                              │
                    [ Validate YAML Schema ]
                              │
                    [ Process Execution ]
                              │
         ┌────────────────────┴────────────────────┐
  [ Foreground Mode ]                       [ Background Mode ]
  (Multiplex to Terminal)                   (Write to Log Files)
         │                                         │
  ├── Thread 1 (stdout)                     ├── .orch/logs/backend.log
  ├── Thread 2 (stdout)                     ├── .orch/logs/frontend.log
  └── SIGINT cleanup                        └── Keep PIDs in .orch/state.json
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
