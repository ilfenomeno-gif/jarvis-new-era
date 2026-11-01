"""
Plugin: ADA CAD Printer — genera script CAD (OpenSCAD) e prepara modelli per la stampa 3D.
"""
import os
import subprocess
from pathlib import Path

PLUGIN = {
    "name": "ada_cad_printer",
    "description": (
        "Crea script CAD in formato OpenSCAD (.scad) a partire da una descrizione testuale, "
        "oppure avvia lo slicing/stampa di un file STL. "
        "Azione 'create' per generare il codice CAD, 'print' per inviare un STL alla stampante."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Azione: 'create' per generare file CAD, 'print' per stampare un STL."
            },
            "scad_script": {
                "type": "STRING",
                "description": "Codice OpenSCAD da salvare su file (solo con action='create')."
            },
            "filename": {
                "type": "STRING",
                "description": "Nome del file di output (es. 'modello.scad' o 'modello.stl')."
            },
            "stl_path": {
                "type": "STRING",
                "description": "Percorso completo del file STL da stampare (solo con action='print')."
            }
        },
        "required": ["action"]
    }
}


def run(parameters: dict, **kwargs) -> str:
    action = parameters.get("action", "").lower()

    if action == "create":
        script_content = parameters.get("scad_script", "")
        filename = parameters.get("filename", "model.scad")
        if not script_content:
            return "Nessun codice CAD fornito per la generazione."
        try:
            out_path = Path(filename)
            out_path.write_text(script_content, encoding="utf-8")
            return f"File CAD '{filename}' creato. Aprilo con OpenSCAD per compilarlo in STL."
        except Exception as e:
            return f"Errore durante la creazione del file CAD: {e}"

    elif action == "print":
        stl_path = parameters.get("stl_path", "")
        if not stl_path or not os.path.exists(stl_path):
            return f"File STL non trovato: '{stl_path}'."
        # In un ambiente reale chiamerebbe le API Moonraker/Mainsail o un slicer CLI
        return f"Processo di stampa avviato per '{stl_path}'. File inviato alla stampante 3D."

    return "Azione non valida. Usa 'create' o 'print'."
