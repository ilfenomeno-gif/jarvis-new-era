import os
from pathlib import Path
from agents.supervisor_agent import _get_model

def read_in_chunks(file_path: str, chunk_size: int = 10000):
    """
    Generator to read a file piece by piece.
    """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

def process_large_file(file_path: str, prompt_instruction: str) -> str:
    """
    Reads a large file in chunks and uses the LLM to summarize/extract info
    based on the prompt instruction.
    """
    p = Path(file_path)
    if not p.exists():
        return f"File non trovato: {file_path}"
    
    model = _get_model()
    results = []
    
    for i, chunk in enumerate(read_in_chunks(file_path)):
        prompt = f"""Task: {prompt_instruction}
        
Part {i+1} of the file:
{chunk}
"""
        try:
            res = model.generate_content(prompt)
            results.append(f"--- Risultato Parte {i+1} ---\n{res.text.strip()}")
        except Exception as e:
            results.append(f"--- Errore Parte {i+1} ---\n{str(e)}")
            
    return "\n\n".join(results)

def large_file_action(parameters: dict, **kwargs) -> str:
    file_path = parameters.get("file_path", "")
    instruction = parameters.get("instruction", "Riassumi questo blocco di testo.")
    if not file_path:
        return "Devi specificare un file_path."
    return process_large_file(file_path, instruction)


TOOL = {
    "name": "large_file_reader",
    "description": "Reads very large files (txt, log, code, etc.) in streaming chunks and processes each chunk with an AI instruction. Use this when a file is too big to read in one shot.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path":   {"type": "STRING", "description": "Absolute path to the file to read."},
            "instruction": {"type": "STRING", "description": "What to do with each chunk (e.g. 'Summarize', 'Find errors', 'Extract names')."},
        },
        "required": ["file_path"]
    },
    "handler": large_file_action,
}
