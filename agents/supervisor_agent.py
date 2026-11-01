import json
import re
from pathlib import Path
import sys

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    from core.api_keys import gemini_api_key
    return gemini_api_key(API_CONFIG_PATH.parent)

def _get_model(model_name: str = "gemini-flash-latest"):
    from google import genai
    import time
    _c = genai.Client(api_key=_get_api_key())
    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model_name, contents=contents)
    return _W()

def run_supervisor(task_description: str) -> dict:
    """
    Supervisor Agent analyzes the task and breaks it down into subtasks for other agents.
    Returns a planned workflow dict.
    """
    model = _get_model()
    prompt = f"""You are the Supervisor Agent of a multi-agent AI coding system.
Analyze the following user task and break it down into steps for the sub-agents:
1. Research Agent: to search documentation and APIs.
2. Coder Agent: to write code.
3. Debugger Agent: to test and fix the code.

Task: {task_description}

Return ONLY valid JSON with this structure:
{{
    "plan_summary": "Brief summary",
    "research_tasks": ["search for X", "check Y"],
    "coding_tasks": ["create module Z", "implement function W"],
    "testing_tasks": ["run tests on Z", "verify W"]
}}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
        text = re.sub(r"\r?\n?```\s*$", "", text)
        return json.loads(text.strip())
    except Exception as e:
        return {"error": str(e), "plan_summary": "Failed to parse plan"}

def supervisor_action(parameters: dict, **kwargs) -> str:
    task = parameters.get("task", "")
    if not task:
        return "Supervisor needs a task."
    plan = run_supervisor(task)
    return json.dumps(plan, indent=2)
