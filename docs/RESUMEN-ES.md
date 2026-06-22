# Resumen de Proyecto: CLI Local Orchestrator (`orch`)

Este documento contiene un resumen completo de las discusiones, decisiones de diseño, arquitectura interna, comandos y flujos de trabajo de **`orch`**, la herramienta CLI de orquestación local diseñada para desarrolladores.

---

## 1. Propósito y Contexto
`orch` es una herramienta ligera de terminal diseñada para orquestar la ejecución de múltiples servicios locales (backends, frontends, agentes, watchers) bajo una arquitectura cliente-servidor, sin requerir contenedores (como Docker) ni demonios persistentes de fondo.

### Problemas que resuelve:
* **Terminales múltiples**: Evita tener que abrir varias consolas de PowerShell, CMD o Bash para un solo proyecto.
* **Activación de venvs**: Activa automáticamente y de forma transparente el entorno virtual (`venv`) de Python correspondiente al proyecto.
* **Logs centralizados**: Unifica las salidas de todos los procesos en tiempo real con prefijos coloreados y legibles.
* **Persistencia en segundo plano**: Permite ejecutar los servicios desacoplados en el fondo del sistema operativo liberando la consola actual.

---

## 2. Modelo de Configuración (`orch.yml`)
El comportamiento de un proyecto se define mediante un archivo de configuración minimalista en formato YAML situado en la raíz del proyecto.

```yaml
project: Windows_Monitor

# Configuración global del entorno
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

## 3. Comandos y Experiencia de Usuario (UX)
El ciclo de vida del proyecto se gestiona mediante dos flujos de trabajo principales:

### Flujo A: Desarrollo Activo e Interactivo (Foreground)
* **Comando**: `orch up`
* **Comportamiento**: Inicia todos los servicios secuencialmente en la consola actual. Multiplexa las salidas de texto de todos los procesos en tiempo real usando hilos individuales en segundo plano.
* **Terminación**: Al presionar `Ctrl+C`, `orch` intercepta la señal y finaliza de manera limpia y recursiva todos los procesos creados (incluyendo subprocesos de Node/Vite).

### Flujo B: Ejecución en Segundo Plano (Background / Detached)
* **Iniciar**: `orch start`  
  Arranca los subprocesos de forma totalmente desacoplada del terminal actual, redirigiendo su salida silenciosamente a archivos `.log` en `.orch/logs/` y liberando la terminal de inmediato.
* **Monitorear**: `orch status`  
  Consulta la base de datos local de estados y comprueba en el sistema operativo si los servicios siguen activos, mostrando una tabla de recursos:
  ```text
             Project: Windows_Monitor (Services Status)
  ┌─────────┬─────────┬───────┬───────┬─────────────┬──────────┐
  │ Service │ Status  │  PID  │ CPU % │ Memory (MB) │  Uptime  │
  ├─────────┼─────────┼───────┼───────┼─────────────┼──────────┤
  │ backend │ RUNNING │ 33284 │  0.0% |    162.1 MB │ 00:00:06 │
  │ ui      │ RUNNING │ 16984 │  0.0% │    178.2 MB │ 00:00:06 │
  │ agent   │ RUNNING │ 20392 │  0.0% │     56.7 MB │ 00:00:06 │
  └─────────┴─────────┴───────┴───────┴─────────────┴──────────┘
  ```
* **Consultar Logs**: `orch logs` / `orch logs -f`  
  Permite leer las últimas líneas de bitácora o seguirlas en tiempo real (multiplexando la cola de múltiples archivos de log a la vez).
* **Detener**: `orch stop`  
  Envía señales de muerte del sistema operativo a todos los servicios en segundo plano y limpia su registro de estado.
* **Limpiar**: `orch clean`  
  Detiene servicios activos, vacía a 0 bytes todos los archivos de logs de la carpeta `.orch/logs/` y reinicia la base de datos de estados.

---

## 4. Arquitectura Interna (Daemon-less)

El diseño de `orch` destaca por ser ligero y confiable gracias a las siguientes soluciones técnicas:

### Activación Dinámica del Entorno Virtual (`venv`)
`orch` no ejecuta scripts de activación tradicionales (como `activate.bat` o `activate.sh`). En su lugar, calcula la ruta absoluta de los ejecutables del `venv` (por ejemplo, `venv/Scripts` en Windows o `venv/bin` en Linux) y la **inyecta al inicio de la variable de entorno `PATH`** del subproceso. Así, cuando el comando llama a `python`, el sistema operativo resuelve y utiliza de forma natural y automática el Python del entorno virtual.

### Persistencia Multiplataforma en Segundo Plano (Windows / Linux)
Para lograr que los procesos sobrevivan al cierre de la terminal del programador de manera independiente sin requerir un demonio persistente corriendo de fondo:
* **En Windows**: Arranca los subprocesos de forma desacoplada utilizando flags nativas de la API de Windows en `subprocess.Popen`:
  - `CREATE_NEW_CONSOLE (0x00000010)`: Asigna una consola exclusiva para evitar que el proceso dependa de la consola padre.
  - `CREATE_NO_WINDOW (0x08000000)`: Oculta la nueva consola para evitar que aparezcan ventanas emergentes al usuario.
  - `CREATE_BREAKAWAY_FROM_JOB (0x01000000)`: Permite al subproceso escapar de los límites del grupo de trabajos de la tarea que lo invocó.
* **En Linux/macOS**: Usa `start_new_session=True` para desvincular el proceso de la sesión actual de la terminal.
* Redirecciona las entradas estándar a `/dev/null` (`DEVNULL`) y las salidas de diagnóstico directamente a los archivos locales de logs.

### Prevención de Conflictos de PIDs Reciclados
El archivo `.orch/state.json` no solo registra el número de PID, sino también la marca de tiempo exacta de creación del proceso en el sistema operativo (`create_time` mediante la librería `psutil`). Al ejecutar comandos de control como `status` o `stop`, se compara el PID actual del sistema operativo con esta marca de tiempo de creación. Si el PID fue reasignado a otro programa totalmente diferente tras cerrarse el servicio, `orch` lo detecta al instante y evita enviar señales de muerte a procesos del sistema equivocados.

### Gestión de Estados
El estado de cada servicio pasa por una de las siguientes etapas:
* **`RUNNING`**: El proceso fue iniciado, su PID existe y coincide en el sistema.
* **`CRASHED`**: El proceso finalizó de forma inesperada (su PID no existe en el sistema, pero el usuario no corrió un comando `stop`).
* **`STOPPED`**: El proceso fue finalizado de forma intencionada mediante un comando de detención (`stop` / `clean`).

### Escapado de Salida en Terminal (Rich Markup)
Para evitar que las salidas de consola de herramientas comunes como Vite o Flask (que suelen usar corchetes y códigos de colores ANSI) interfieran con el motor de formato de `Rich`, todos los mensajes de bitácora son procesados con la función `rich.markup.escape()`. Asimismo, los corchetes de los prefijos se protegen con caracteres de escape (`\\[`) permitiendo que el formato en colores de los nombres de servicio se renderice correctamente en cualquier tipo de terminal de desarrollo.
