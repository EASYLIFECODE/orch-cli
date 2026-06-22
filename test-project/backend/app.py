import time
import sys
import os

print("Backend started successfully!", flush=True)
print(f"Current Working Directory: {os.getcwd()}", flush=True)
print(f"Virtual Env Active: {os.environ.get('VIRTUAL_ENV', 'NONE')}", flush=True)
print(f"PATH variable: {os.environ.get('PATH', '')[:100]}...", flush=True)

try:
    for i in range(1, 15):
        print(f"[API] Serving request #{i} - Database connected", flush=True)
        time.sleep(1)
except KeyboardInterrupt:
    print("Backend received SIGINT, exiting gracefully...", flush=True)
    sys.exit(0)

print("Backend completed task loop.", flush=True)
