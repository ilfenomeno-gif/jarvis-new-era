# JARVIS VII

Assistente desktop AI personale (Windows-first), fusione di:

- **B** — [`ilfenomeno-gif/jarvis-new-gen`](https://github.com/ilfenomeno-gif/jarvis-new-gen) (`Mark-LIV-main`, baseline `origin/main` @ `41e405e`): app desktop PyQt6 + Gemini Live, sicurezza (guardrail, DPAPI, audit, conferme UI), plugin, multi-agente, GEV, 3D, ~55 file di test.
- **C** — [`FatihMakes/Mark-LVI`](https://github.com/FatihMakes/Mark-LVI) (@ `4d4035c`): layer `providers/` (motore STT+LLM+TTS intercambiabile con fallback a Gemini Live), protocollo `outcome` (done/unverified/failed), dashboard HTTPS+AES-GCM, avatar olografico.
- **A** — n8n Cloud come **motore di workflow** via webhook (canale solo outbound; eventi n8n→desktop via polling "outbox").

**Architettura**: Opzione 2 — *Python come cervello, n8n come motore di workflow*. Il realtime vocale resta sul desktop; n8n orchestra flussi/integrazioni/schedulazioni come tool remoto.

## Cosa c'è di nuovo rispetto a B

| Area | Aggiunta | File |
|---|---|---|
| Motore intercambiabile | `providers/` (Ollama, Whisper, Piper, OpenAI-compat…) con fallback automatico a Gemini Live | `providers/`, `main.py` (`_engine_mode`/`_resolve_engine_caps`/`_open_session`) |
| Esiti onesti | protocollo `done/unverified/failed/ask/started` + wrapper anti prompt-injection | `core/outcome.py` |
| Config provider | modalità `gemini`/`pipeline`, pipeline STT/LLM/TTS, sidecar, plugin_config | `memory/config_manager.py` |
| Dashboard indurita | HTTPS self-signed obbligatorio + AES-256-GCM (PBKDF2 200k) | `dashboard/server.py` |
| n8n Bridge | azione `n8n_bridge` (HTTPS, header auth, timeout, outcome, audit, payload solo testo) | `actions/n8n_bridge.py`, `docs/n8n/` |
| n8n → desktop | polling "outbox" (nessuna porta aperta), notifica HUD/log | `core/n8n_outbox.py` |
| Sandbox plugin | sottoprocesso + IPC JSON dichiarativa, opt-in `PLUGIN["sandboxed"]` | `core/plugin_sandbox.py`, `core/_plugin_sandbox_worker.py` |
| Redaction estesa | JWT, AWS, Bearer, GitHub PAT | `core/guardrails.py` |
| Avatar olografico | opt-in via `hud_style="face"` (default `core` invariato) | `ui.py`, `core/avatar.py` |

## Stato dei test

Suite `pytest -q -m 'not live'`: **719 passed, 14 skipped, 3 failed**.
I 3 failed sono in `tests/test_viewer3d.py` e sono **preesistenti nella baseline** `origin/main`
(`ui.py` chiama `core.viewer3d.save_screenshot`, che non esiste; i test richiedono stack GPU/QtWebEngine reale). Non causati dalle modifiche P0–P5.

## Documenti

- `docs/n8n/README.md` — configurazione del bridge n8n e workflow "echo" di prova.
- `NOTICE` — attribuzioni e licenze.
- `INSTALL_WINDOWS.md` — guida di installazione.
- `SECURITY.md` — checklist di sicurezza.
- `LIMITI.md` — limiti noti e parti DA VERIFICARE.

## Licenza

Uso **personale / non commerciale**. Componenti sotto CC BY-NC 4.0 (© FatihMakes), GEV MIT, ASTRALIS Apache-2.0. Vedi `NOTICE` e `LICENSE`.
