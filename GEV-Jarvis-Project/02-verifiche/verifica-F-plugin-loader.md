# Verifica F — Plugin loader

## Obiettivo

Verificare hook lifecycle, ordine, error isolation e disponibilità di test.

## Cosa è stato verificato

`start_all()` scorre `_plugins.items()` e intercetta eccezioni per plugin. `stop_all()` scorre gli hook in ordine inverso, usa un `ThreadPoolExecutor(max_workers=1)` e un timeout globale; segnala le eccezioni tramite logger. Le funzioni `start`/`stop` sono opzionali nel record plugin (`core/plugin_loader.py:48-88`, `:147-181`).

## Come

- Letti `core/plugin_loader.py:41-89`, `:147-181`.
- Controllata la presenza di `tests/test_plugin_lifecycle.py`: assente.
- Elencati i file test: `tests/test_writing_assistant.py` è il solo file di test Python presente.

## Risultato e stato

**Verificato staticamente**: ordine/error isolation a livello di codice. Il test lifecycle richiesto non esiste nel checkout: nessun estratto da `tests/test_plugin_lifecycle.py` è disponibile. Nessun test è stato eseguito.

> Da verificare: test automatizzati dedicati per ordine di avvio/stop, eccezione e timeout.

