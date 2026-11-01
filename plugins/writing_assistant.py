"""
Plugin per migliorare testi usando l'API di DeepSeek.
Supporta file .md, .txt, .docx, e .pdf.
Preserva nativamente e in-place la formattazione avanzata dei file .docx (stili, run, tabelle, header/footer).
"""

import os
import shutil
import textwrap
import re
import time
import difflib
import random
from datetime import datetime
from typing import Optional, Any

# Dipendenze opzionali gestite a runtime
try:
    import openai
except ImportError:
    openai = None

try:
    import docx
except ImportError:
    docx = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

PLUGIN = {
    "name": "gestisci_testo",
    "description": (
        "Usa DeepSeek per migliorare la scrittura di un file di testo (.md, .txt, .docx, .pdf). "
        "Migliora grammatica, sintassi, lessico e ritmo, mantenendo contenuto, contesto e trama intatti. "
        "Permette anche di annullare l'ultima modifica se l'utente lo richiede ('annulla')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Percorso assoluto o relativo del file da migliorare."
            },
            "istruzioni": {
                "type": "STRING",
                "description": "Istruzioni opzionali su come migliorare il testo (es. 'rendi più formale', 'aumenta suspense')."
            },
            "stile_target": {
                "type": "STRING",
                "description": "Stile desiderato (es. 'formale', 'narrativo', 'saggistico', 'poetico')."
            },
            "azione": {
                "type": "STRING",
                "description": "L'azione da eseguire. Può essere 'migliora' (default) o 'annulla' (per ripristinare il backup).",
                "enum": ["migliora", "annulla"]
            }
        },
        "required": ["file_path"]
    }
}

# Limite conservativo per i caratteri nei chunk (circa 6000-8000 token)
CHUNK_MAX_CHARS = 24000


def _log(player, message: str) -> None:
    """Scrive un messaggio nel log del player se disponibile."""
    if player and hasattr(player, "write_log"):
        player.write_log(message)


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """
    Divide il testo in chunk rispettando i paragrafi (doppi newline).
    Se un paragrafo è troppo lungo, lo spezza con textwrap.
    """
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) + 2 > max_chars:
            if current:
                chunks.append(current)
            if len(p) > max_chars:
                subchunks = textwrap.wrap(
                    p, width=max_chars,
                    replace_whitespace=False,
                    drop_whitespace=False
                )
                chunks.extend(subchunks)
                current = ""
            else:
                current = p
        else:
            if current:
                current += "\n\n" + p
            else:
                current = p

    if current:
        chunks.append(current)
    return chunks


def _mask_code_blocks(text: str) -> tuple[str, dict]:
    """Sostituisce i code block markdown con dei placeholder per proteggerli dal LLM."""
    placeholders = {}
    
    def replacer(match):
        ph = f"[[[CODE_BLOCK_{len(placeholders)}]]]"
        placeholders[ph] = match.group(0)
        return ph

    masked_text = re.sub(r'```.*?```', replacer, text, flags=re.DOTALL)
    return masked_text, placeholders


def _unmask_code_blocks(text: str, placeholders: dict) -> str:
    """Ripristina i code block al posto dei placeholder."""
    for ph, original in placeholders.items():
        text = text.replace(ph, original)
    return text


def _extract_frontmatter(text: str) -> tuple[str, str]:
    """
    Estrae il frontmatter YAML se presente all'inizio del testo.
    Restituisce una tupla (frontmatter, testo_senza_frontmatter).
    Il frontmatter include i delimitatori '---'.
    """
    match = re.match(r'^(?:\s*)(---.*?---)(?:\s*\n+)(.*)', text, flags=re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return "", text


def _read_file(file_path: str) -> tuple[Any, str]:
    """Legge il file. Per DOCX ritorna l'oggetto Document, per gli altri stringhe."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in ['.txt', '.md']:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read(), ext
    elif ext == '.docx':
        if docx is None:
            raise ImportError("Libreria 'python-docx' non installata.")
        doc = docx.Document(file_path)
        return doc, ext
    elif ext == '.pdf':
        if pdfplumber is None:
            raise ImportError("Libreria 'pdfplumber' non installata.")
        text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text.append(extracted)
        return "\n".join(text), ext
    else:
        raise ValueError(f"Formato file non supportato: {ext}")


def _write_file(file_path: str, content: str, original_ext: str) -> str:
    """Scrive file .md o .txt (Il .docx è gestito in-place)."""
    if original_ext == '.pdf':
        file_path = os.path.splitext(file_path)[0] + "_migliorato.md"

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return file_path


def _generate_diff_log(original: str, improved: str, file_path: str, player) -> None:
    """Genera e logga un breve riepilogo delle modifiche (diff)."""
    orig_lines = original.splitlines()
    imp_lines = improved.splitlines()
    diff = list(difflib.unified_diff(orig_lines, imp_lines, lineterm=""))
    
    # Non mostriamo un diff enorme, contiamo solo le modifiche
    additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    
    _log(player, f"JARVIS: Analisi differenze per {os.path.basename(file_path)}:")
    _log(player, f"JARVIS: {additions} linee aggiunte/modificate, {deletions} linee rimosse.")
    if len(diff) > 0 and len(diff) < 20:
        _log(player, f"JARVIS: Dettaglio diff:\n" + "\n".join(diff))


def _call_deepseek_with_retry(client, messages, max_retries=3):
    """Chiama l'API DeepSeek gestendo errori di rete o rate limits tramite retry e backoff con jitter."""
    delay = 2
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                timeout=30.0
            )
            return response.choices[0].message.content
        except openai.RateLimitError as e:
            if "insufficient_quota" in str(e).lower() or "quota" in str(e).lower():
                raise RuntimeError("Quota API DeepSeek esaurita o credito insufficiente.")
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay + random.uniform(0, 1))
            delay *= 2
        except (openai.APIConnectionError, openai.APIError) as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay + random.uniform(0, 1))
            delay *= 2
    return ""


def _process_text_with_deepseek(text: str, istruzioni: str, stile: str) -> str:
    """Invia il testo a DeepSeek, dividendo in chunk se troppo lungo, e ricompone il risultato."""
    if openai is None:
        raise ImportError("Libreria 'openai' non installata.")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("Chiave API DEEPSEEK_API_KEY non trovata nelle variabili d'ambiente.")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )

    system_prompt = (
        "Sei un editor professionista ed esperto di scrittura. Il tuo compito è migliorare il testo fornito, "
        "intervenendo su grammatica, sintassi, lessico e ritmo.\n"
        "REGOLE FONDAMENTALI:\n"
        "1. Devi preservare rigorosamente il contenuto originale, il contesto, la trama e il significato.\n"
        "2. Non aggiungere nuove informazioni, non rimuovere dettagli chiave e non alterare la voce dell'autore se non per migliorarne la fluidità.\n"
        "3. Se ti viene fornito un testo molto breve, non allungarlo inutilmente.\n"
        "4. PRESERVA IL MARKDOWN: Non alterare o rompere formattazioni come tabelle, code blocks (```), link ([testo](url)) o immagini."
    )

    if stile:
        system_prompt += f"\n5. Applica il seguente stile target: {stile}."
    if istruzioni:
        system_prompt += f"\n6. Segui queste istruzioni aggiuntive: {istruzioni}."

    # Mascheramento dei code block
    masked_text, placeholders = _mask_code_blocks(text)

    if len(masked_text) <= CHUNK_MAX_CHARS:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Migliora il seguente testo:\n\n{masked_text}"}
        ]
        improved_text = _call_deepseek_with_retry(client, messages)
        return _unmask_code_blocks(improved_text, placeholders)

    chunks = _split_into_chunks(masked_text, CHUNK_MAX_CHARS)
    improved_chunks = []
    context_summary = "Inizio del testo."

    for i, chunk in enumerate(chunks):
        chunk_prompt = (
            f"Contesto precedente (non modificarlo, usalo solo per capire di cosa stiamo parlando): {context_summary}\n\n"
            f"Testo da migliorare (PARTE {i+1}/{len(chunks)}):\n\n{chunk}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chunk_prompt}
        ]
        improved_text = _call_deepseek_with_retry(client, messages)
        
        if improved_text:
            improved_chunks.append(improved_text)

        if i < len(chunks) - 1 and improved_text:
            summary_messages = [
                {"role": "system", "content": "Sei un assistente che riassume brevemente il contesto della storia o documento finora elaborato, per mantenere coerenza."},
                {"role": "user", "content": f"Genera un riassunto di massimo 2-3 frasi di questo testo per dare contesto alla parte successiva:\n\n{improved_text}"}
            ]
            summary_text = _call_deepseek_with_retry(client, summary_messages)
            context_summary = summary_text or context_summary

    final_improved_text = "\n\n".join(improved_chunks)
    return _unmask_code_blocks(final_improved_text, placeholders)


def _replace_paragraph_text_preserving_runs(paragraph, improved_text: str):
    """
    Sostituisce il testo di un paragrafo docx spalmando il nuovo testo sui run esistenti.
    Mantiene intatte formattazioni (grassetto, corsivo, ecc.).
    """
    if not paragraph.runs:
        if improved_text:
            paragraph.add_run(improved_text)
        return

    original_text = paragraph.text
    if not original_text:
        paragraph.runs[0].text = improved_text
        return

    # Calcoliamo le proporzioni basate sui caratteri per distribuire i nuovi stili
    run_ratios = [len(r.text) / len(original_text) for r in paragraph.runs]
    
    # Svuotiamo i run esistenti senza distruggerli
    for r in paragraph.runs:
        r.text = ""
        
    start = 0
    total_len = len(improved_text)
    
    for i, ratio in enumerate(run_ratios):
        if i == len(run_ratios) - 1:
            # Ultimo run prende tutto il resto per evitare troncamenti per arrotondamento
            paragraph.runs[i].text = improved_text[start:]
        else:
            chunk_len = int(total_len * ratio)
            paragraph.runs[i].text = improved_text[start:start+chunk_len]
            start += chunk_len


def _process_docx_inplace(doc, istruzioni, stile_target, player):
    """
    Itera su tutti gli elementi testuali di un docx (paragrafi, tabelle, intestazioni),
    migliorandoli e preservando lo stile in-place. Restituisce il testo aggregato per il log diff.
    """
    original_full_text = []
    improved_full_text = []
    
    def process_paragraph(p):
        text = p.text.strip()
        if not text:
            return
        original_full_text.append(text)
        # Migliora e rimappa il testo formattato
        improved = _process_text_with_deepseek(text, istruzioni, stile_target)
        improved_full_text.append(improved)
        _replace_paragraph_text_preserving_runs(p, improved)
        
    for p in doc.paragraphs:
        process_paragraph(p)
        
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    process_paragraph(p)
                    
    for section in doc.sections:
        for p in section.header.paragraphs:
            process_paragraph(p)
        for p in section.footer.paragraphs:
            process_paragraph(p)
            
    return "\n".join(original_full_text), "\n".join(improved_full_text)


def _handle_annulla(file_path: str, player) -> str:
    """Gestisce l'azione di annullamento ripristinando l'ultimo backup versionato."""
    directory = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)
    backups = [f for f in os.listdir(directory) if f.startswith(base_name + ".bak")]
    
    if not backups:
        return "Signore, non ho trovato alcun backup per annullare l'operazione su questo file."
    
    # Prende il backup più recente in ordine alfabetico/timestamp
    latest_backup = sorted(backups)[-1]
    backup_path = os.path.join(directory, latest_backup)
    
    shutil.copy2(backup_path, file_path)
    _log(player, f"JARVIS: Ripristinato il file dal backup: {latest_backup}.")
    return f"Ho annullato con successo le ultime modifiche su {base_name} e ripristinato l'originale."


def run(parameters: dict, player=None, session_memory=None) -> str:
    file_path = parameters.get("file_path", "")
    istruzioni = parameters.get("istruzioni", "")
    stile_target = parameters.get("stile_target", "")
    azione = parameters.get("azione", "migliora")

    if not file_path:
        return "Signore, non mi ha fornito il percorso del file."

    file_path = os.path.abspath(os.path.expanduser(file_path))

    if not os.path.exists(file_path):
        return f"Signore, non riesco a trovare il file specificato: {file_path}"
        
    if azione == "annulla":
        return _handle_annulla(file_path, player)

    try:
        _log(player, f"JARVIS: Sto leggendo il file {os.path.basename(file_path)}...")

        original_content, original_ext = _read_file(file_path)

        # Controllo che il contenuto (se testuale) non sia vuoto
        if original_ext != '.docx' and not original_content.strip():
            return "Signore, il file indicato sembra essere vuoto."

        # Backup versionato (Ora valido anche per .docx!)
        if original_ext in ['.txt', '.md', '.docx']:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = file_path + f".bak_{timestamp}"
            shutil.copy2(file_path, backup_path)
            
            # Pulizia vecchi backup (mantieni ultimi 5)
            directory = os.path.dirname(file_path)
            base_name = os.path.basename(file_path)
            backups = sorted([f for f in os.listdir(directory) if f.startswith(base_name + ".bak_")])
            if len(backups) > 5:
                for vecchi in backups[:-5]:
                    os.remove(os.path.join(directory, vecchi))
            
            _log(player, f"JARVIS: Ho creato una copia di backup versionata in {os.path.basename(backup_path)} (mantenuti ultimi 5).")

        _log(player, "JARVIS: Sto inviando il testo a DeepSeek per il miglioramento (con gestione errori abilitata). L'operazione potrebbe richiedere qualche istante...")

        if original_ext == '.docx':
            # Gestione specializzata In-Place per MS Word
            orig_text_log, imp_text_log = _process_docx_inplace(original_content, istruzioni, stile_target, player)
            original_content.save(file_path)
            _generate_diff_log(orig_text_log, imp_text_log, file_path, player)
            return f"Ho migliorato il file .docx {os.path.basename(file_path)} preservandone stili, tabelle e formattazione originaria. Se non ti piace, chiedimi di annullare."
        else:
            # Flusso testuale classico
            frontmatter, clean_text = _extract_frontmatter(original_content)
            improved_clean_text = _process_text_with_deepseek(clean_text, istruzioni, stile_target)
            improved_text = frontmatter + improved_clean_text if frontmatter else improved_clean_text
            
            _generate_diff_log(original_content, improved_text, file_path, player)
            output_path = _write_file(file_path, improved_text, original_ext)

            if output_path != file_path:
                return f"Ho estratto e migliorato il testo, salvandolo in un nuovo file: {os.path.basename(output_path)}."
            else:
                return f"Ho migliorato il file {os.path.basename(file_path)} con successo. Se non ti piace, chiedimi di annullare le modifiche."

    except openai.RateLimitError:
        return "Signore, abbiamo raggiunto il limite di richieste di DeepSeek. Riprovi tra poco."
    except openai.APIConnectionError:
        return "Signore, ho riscontrato un problema di connessione con i server di DeepSeek."
    except ImportError as ie:
        return f"Signore, manca una libreria necessaria: {ie}. Assicurati di aver installato openai, python-docx e pdfplumber."
    except ValueError as ve:
        return f"Signore, ho riscontrato un problema: {ve}"
    except Exception as e:
        return f"Signore, il plugin di scrittura assistita ha riscontrato un errore imprevisto: {str(e)}"
