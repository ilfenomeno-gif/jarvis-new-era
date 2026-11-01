# Verifica C — Struttura async

## Obiettivo

Controllare come il lifecycle plugin interagisce con il loop asyncio e i thread.

## Cosa è stato verificato

**Verificato nel codice**: `run()` salva il loop e il task corrente; la cancellazione da `main()` passa per `loop_ref.call_soon_threadsafe(task_ref.cancel)`. Lo start dei plugin avviene su thread daemon. `_shutdown_event` e `_plugins_stopped_evt` sono `threading.Event`; il loader invoca `stop_all(timeout=5.0)` una sola volta quando l'evento non è set.

## Come

- Lettura `main.py:931-940`, `:2065-2069`, `:2268-2310`.
- Lettura lifecycle `core/plugin_loader.py:48-88`.
- Consultato commit `29c198de07ecbabbce95674d6028e7be5f3cc5d9`.

## Risultato e stato

**Verificato**: meccanismi e punti di sincronizzazione statici. Non è stata eseguita una prova concorrente, né misurata la chiusura in runtime.

> Da verificare: comportamento con cancellazione durante avvio/install GEV e con stop hook che supera il timeout.

