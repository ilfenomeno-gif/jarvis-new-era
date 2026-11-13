# Installazione su Windows — JARVIS VII

## Prerequisiti

- Windows 10/11.
- **Python 3.11+** (verificato fino a 3.13.7). La compatibilità oltre dipende dalle dipendenze native.
- Microfono e altoparlanti.
- Una **chiave API Gemini** (per il motore vocale di default). Per il motore locale: vedi §4.

## Installazione

```powershell
git clone <questo-repo> jarvis-vii-app
cd jarvis-vii-app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install
```

## Configurazione della chiave Gemini (DPAPI, mai in chiaro)

All'avvio la schermata di setup salva la chiave nel **SecretStore DPAPI** (`config/secrets.json`,
cifrato per-utente Windows). Per migrare una chiave esistente da `config/api_keys.json`:

```powershell
python -c "from core.api_keys import migrate; print(migrate(remove_plain=True))"
```

## Avvio

```powershell
.\.venv\Scripts\python.exe main.py
```

`main.py` rileva anche un avvio accidentale con Python globale e rilancia Jarvis
con `.venv\Scripts\python.exe`. Puoi verificare interprete e dipendenze senza
avviare l'interfaccia:

```powershell
python main.py --check-startup
```

Se manca una dipendenza richiesta, Jarvis si ferma prima di caricare l'interfaccia
e indica di eseguire `pip install -r requirements.txt` nell'ambiente virtuale.

### Avvio automatico (facoltativo)

Per avviare Jarvis all'accesso dell'utente Windows, esegui:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart.ps1
```

Lo script crea una scorciatoia nella cartella Startup dell'utente corrente,
usando `pythonw.exe` della `.venv` e avviando la finestra minimizzata. Non
termina né modifica altri processi. Per rimuoverla:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart.ps1 -Uninstall
```

### Dipendenze mancanti durante un'azione

Se un'azione segnala un modulo Python mancante, Jarvis propone l'installazione.
Solo dopo la conferma installa il pacchetto se è già dichiarato in
`requirements.txt`, usando `python -m pip` dell'ambiente virtuale, quindi riprova
l'azione una sola volta. Se il modulo non corrisponde a una dipendenza del
progetto, l'installazione viene rifiutata e l'errore viene mostrato.

Il watchdog controlla solamente i processi MCP avviati e posseduti da Jarvis;
se il server Public APIs si interrompe, ne avvia una nuova istanza. Non termina
processi esterni né altre istanze dell'applicazione.

## 4. Motore locale (opzionale, privacy)

Per non mandare il microfono a Gemini: ⚙ → *ENGINE & PROVIDERS* → modalità **pipeline**
(STT Whisper + LLM OpenAI-compatibile es. Ollama + TTS Piper). Dipendenze opzionali:

```powershell
pip install faster-whisper piper-tts
```

Se la pipeline non parte, JARVIS VII torna **automaticamente** a Gemini Live.

## 5. n8n Bridge (opzionale)

Vedi `docs/n8n/README.md`: importa `docs/n8n/echo-workflow.json` in n8n Cloud, crea
`config/n8n.json`, memorizza il segreto del webhook nel SecretStore DPAPI.

## 6. Avatar olografico (opzionale)

```powershell
python -c "from memory.config_manager import save_hud_style; save_hud_style('face')"
```

Per tornare al reactor core: `save_hud_style('core')` (default).

## Test

```powershell
python -m pytest -q -m "not live"
```
