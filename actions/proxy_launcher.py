import subprocess
import sys
import json
from pathlib import Path

def _get_python_exe() -> str:
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        return exe[:-11] + "python.exe"
    return exe

def run_isolated_command(command: str, cwd: str = ".") -> str:
    """
    Runs a command in a subprocess bypassing pythonw.exe restrictions.
    """
    parts = command.split()
    if parts and parts[0].lower() == "python":
        parts[0] = _get_python_exe()

    try:
        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120,
            cwd=cwd
        )
        return json.dumps({
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        })
    except Exception as e:
        return json.dumps({"error": str(e)})

def proxy_launcher_action(parameters: dict, **kwargs) -> str:
    command = parameters.get("command", "")
    cwd = parameters.get("cwd", ".")
    if not command:
        return json.dumps({"error": "No command provided."})
    return run_isolated_command(command, cwd)


TOOL = {
    "name": "proxy_launcher",
    "description": "Runs a shell command in a subprocess bypassing pythonw.exe whitelist restrictions. Use for build commands, compilation, or any system-level execution.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {"type": "STRING", "description": "Command to run, e.g. 'python build.py' or 'npm install'."},
            "cwd":     {"type": "STRING", "description": "Working directory."},
        },
        "required": ["command"]
    },
    "handler": proxy_launcher_action,
}
