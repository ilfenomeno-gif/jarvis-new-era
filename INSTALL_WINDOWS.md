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
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install
```

## Configurazione della chiave Gemini (DPAPI, mai in chiaro)

All'avvio la schermata di setup salva la chiave nel **SecretStore DPAPI** (`config/secrets.json`,
cifrato per-utente Windows). Per migrare una chiave esistente da `config/api_keys.json`:

```powershell
python -c "from core.api_keys import migrate; print(migrate(remove_plain=True))"
```

## Avvio

```powershell
python main.py
```

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
