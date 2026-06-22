# Project Summary: CLI Local Orchestrator (`orch`)

This document contains a comprehensive summary of the discussions, design decisions, internal architecture, commands, and workflows of **`orch`**, the local orchestration CLI tool designed for developers.

---

## 1. Purpose and Context
`orch` is a lightweight terminal tool designed to orchestrate the execution of multiple local services (backends, frontends, agents, watchers) under a client-server architecture, without requiring containerization (like Docker) or persistent background daemon services.

### Problems it solves:
* **Multiple terminals**: Avoids having to open multiple PowerShell, CMD, or Bash windows for a single project.
* **Virtualenv activation**: Automatically and transparently activates the Python virtual environment (`venv`) corresponding to the project.
* **Centralized logs**: Unifies the outputs of all processes in real-time with colored, readable prefixes.
* **Background persistence**: Allows running decoupled services in the background of the operating system, freeing up the current console.

---

## 2. Configuration Model (`orch.yml`)
The project behavior is defined through a minimalist YAML configuration file located at the project root.

```yaml
project: Windows_Monitor

# Global environment configuration
env:
  type: venv
  path: ./venv-wind_monitor
  variables:
    GLOBAL_TEST_VAR: "orch-is-working"

services:
  backend:
    path: ./backend
    command: python app.py
    env:
      BACKEND_PORT: "8000"

  ui:
    path: ./ui
    command: npm run dev

  agent:
    path: ./agent
    command: python agent.py
```

---

## 3. Commands and User Experience (UX)
The project lifecycle is managed through two main workflows:

### Workflow A: Active & Interactive Development (Foreground)
* **Command**: `orch up`
* **Behavior**: Starts all services sequentially in the current console. Multiplexes the text outputs of all processes in real-time using individual background threads.
* **Termination**: When pressing `Ctrl+C`, `orch` intercepts the signal and cleanly and recursively terminates all created processes (including Node/Vite sub-processes).

### Workflow B: Background Execution (Background / Detached)
* **Start**: `orch start`  
  Spawns sub-processes completely decoupled from the current terminal, silently redirecting their output to `.log` files in `.orch/logs/` and releasing the terminal immediately.
* **Monitor**: `orch status`  
  Queries the local state database and checks the operating system to see if the services are still active, showing a resource table:
  ```text
             Project: Windows_Monitor (Services Status)
  ┌─────────┬─────────┬───────┬───────┬─────────────┬──────────┐
  │ Service │ Status  │  PID  │ CPU % │ Memory (MB) │  Uptime  │
  ├─────────┼─────────┼───────┼───────┼─────────────┼──────────┐
  │ backend │ RUNNING │ 33284 │  0.0% │    162.1 MB │ 00:00:06 │
  │ ui      │ RUNNING │ 16984 │  0.0% │    178.2 MB │ 00:00:06 │
  │ agent   │ RUNNING │ 20392 │  0.0% │     56.7 MB │ 00:00:06 │
  └─────────┴─────────┴───────┴───────┴─────────────┴──────────┘
  ```
* **Check Logs**: `orch logs` / `orch logs -f`  
  Allows reading the last log lines or following them in real-time (multiplexing the queue of multiple log files at once).
* **Stop**: `orch stop`  
  Sends termination OS signals to all background services and cleans up their state registry.
* **Clean**: `orch clean`  
  Stops active services, truncates all log files in the `.orch/logs/` folder to 0 bytes, and resets the state database.

---

## 4. Internal Architecture (Daemon-less)

The design of `orch` stands out for being lightweight and reliable thanks to the following technical solutions:

### Dynamic Virtual Environment Activation (`venv`)
`orch` does not execute traditional activation scripts (like `activate.bat` or `activate.sh`). Instead, it calculates the absolute path of the `venv` executables (e.g., `venv/Scripts` on Windows or `venv/bin` on Linux) and **injects it at the beginning of the `PATH` environment variable** of the sub-process. Thus, when the command calls `python`, the operating system naturally and automatically resolves and uses the Python executable from the virtual environment.

### Multiplatform Background Persistency (Windows / Linux)
To ensure processes survive the closing of the developer's terminal independently without requiring a persistent daemon running in the background:
* **On Windows**: Spawns sub-processes in a decoupled manner using native Windows API flags in `subprocess.Popen`:
  - `CREATE_NEW_CONSOLE (0x00000010)`: Assigns an exclusive console to prevent the process from depending on the parent console.
  - `CREATE_NO_WINDOW (0x08000000)`: Hides the new console to prevent pop-up windows from bothering the user.
  - `CREATE_BREAKAWAY_FROM_JOB (0x01000000)`: Allows the sub-process to escape the limits of the job group of the calling task.
* **On Linux/macOS**: Uses `start_new_session=True` to decouple the process from the current terminal session.
* Redirects standard input to `/dev/null` (`DEVNULL`) and diagnostics outputs directly to local log files.

### Recycled PID Conflict Prevention
The `.orch/state.json` file records not only the PID number but also the exact operating system process creation timestamp (`create_time` using the `psutil` library). When running control commands like `status` or `stop`, the current OS process PID is compared with this creation timestamp. If the PID was reassigned to a completely different program after the service closed, `orch` detects it instantly and avoids sending kill signals to the wrong system processes.

### State Management
The state of each service passes through one of the following stages:
* **`RUNNING`**: The process was started, its PID exists and matches in the system.
* **`CRASHED`**: The process finished unexpectedly (its PID does not exist in the system, but the user did not run a `stop` command).
* **`STOPPED`**: The process was terminated intentionally through a stop command (`stop` / `clean`).

### Terminal Output Escaping (Rich Markup)
To prevent terminal outputs from common tools like Vite or Flask (which usually use square brackets and ANSI color codes) from interfering with the formatting engine of `Rich`, all log messages are processed using the `rich.markup.escape()` function. Additionally, the square brackets of the prefixes are protected with escape characters (`\\[`), allowing the colored format of service names to render correctly in any development terminal.
