# Passo 2 — Lifecycle nel plugin loader

## Obiettivo

Consentire a plugin validi di dichiarare hook `start()` e `stop()`.

## File toccati

- `core/plugin_loader.py`
- `docs/GEV_INTEGRATION.md`

## Modifiche chiave e commit

Commit `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8` — `feat: add plugin lifecycle hooks`. `_validate` acquisisce hook opzionali (`core/plugin_loader.py:170-181`); `start_all()` avvia in ordine e isola eccezioni (`:48-56`); `stop_all()` arresta inversamente con timeout globale e logging (`:59-88`).

## Test e note

Output test: non eseguiti. `tests/test_plugin_lifecycle.py` non esiste nella repo osservata. La doc indica che un thread stop già in esecuzione non è cancellabile dal Future (`docs/GEV_INTEGRATION.md:1-16`).

> Da verificare: test con plugin finti per ordine, errore, timeout e hook opzionali.

