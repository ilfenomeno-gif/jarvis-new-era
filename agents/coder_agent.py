import json
import re
from pathlib import Path
from .supervisor_agent import _get_model

def run_coder(task: str, context: str, file_path: str) -> str:
    """
    Coder Agent writes structured code (AST-aware stub generation).
    """
    model = _get_model("gemini-flash-latest")
    prompt = f"""You are the Coder Agent. Write the complete, runnable code for the given task.
Context from Research: {context}
Task: {task}
Target File: {file_path}

Rules:
- Return ONLY raw code, no markdown backticks, no explanations.
- Write production-ready code.
"""
    try:
        response = model.generate_content(prompt)
        code = response.text.strip()
        code = re.sub(r"^```[a-zA-Z]*\r?\n?", "", code)
        code = re.sub(r"\r?\n?```\s*$", "", code)
        
        if file_path:
            from core.confirm import request as confirm_request
            p = Path(file_path)
            
            def do_write():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(code, encoding="utf-8")
                return f"Nuovo tool generato e scritto in {file_path}"
                
            return confirm_request(
                key="tool_maker",
                title=f"Autorizza creazione del tool: {p.name}",
                detail=f"Sto per generare e installare un nuovo plugin/script in {file_path}. Consentire l'operazione?",
                run=do_write
            )
        return code
    except Exception as e:
        return f"Coder error: {e}"

def coder_action(parameters: dict, **kwargs) -> str:
    task = parameters.get("task", "")
    context = parameters.get("context", "")
    file_path = parameters.get("file_path", "")
    if not task:
        return "Coder Agent needs a task."
    return run_coder(task, context, file_path)
