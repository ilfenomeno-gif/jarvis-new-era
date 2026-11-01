import subprocess
import json
import sys
from .supervisor_agent import _get_model

def run_debugger(command: str, cwd: str) -> str:
    """
    Debugger Agent runs compilation/tests and parses output.
    """
    print(f"[Debugger Agent] Running: {command} in {cwd}")
    try:
        parts = command.split()
        if parts[0].lower() == "python":
            parts[0] = sys.executable
            if parts[0].lower().endswith("pythonw.exe"):
                parts[0] = parts[0][:-11] + "python.exe"

        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=60,
            cwd=cwd
        )
        
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        if result.returncode == 0:
            return f"Success.\nSTDOUT:\n{stdout}"
        
        model = _get_model()
        prompt = f"""You are the Debugger Agent. Analyze the following error output and suggest a fix.
Command: {command}
Return Code: {result.returncode}
STDOUT:
{stdout}
STDERR:
{stderr}
"""
        response = model.generate_content(prompt)
        return f"Error Analysis:\n{response.text.strip()}"

    except Exception as e:
        return f"Debugger exception: {e}"

def debugger_action(parameters: dict, **kwargs) -> str:
    command = parameters.get("command", "")
    cwd = parameters.get("cwd", ".")
    if not command:
        return "Debugger Agent needs a command to run."
    return run_debugger(command, cwd)
