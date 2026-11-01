# Passo 4b — Dispatcher GEV

## Obiettivo

Validare azioni GEV e inviare un messaggio alla UI.

## Stato e file toccati

**Parzialmente presente solo nella working tree Jarvis**, nel diff non committato di `plugins/gev_plugin.py`. La versione committata in `bbdcff8` descrive il dispatcher come placeholder (`plugins/gev_plugin.py:1-4` al commit; `git show bbdcff8:plugins/gev_plugin.py`). Working-tree `git diff -- plugins/gev_plugin.py` aggiunge parametri e `run()` che valida `open`, `track`, `layer`, `reset`, `annotate` e invoca `player.send_to_gev(message)`.

## Modifiche chiave nel diff locale

- Schema ampliato con `target_type`, `target_id`, `layer`, `enabled`, `lat`, `lon`, `text`.
- Validazione di coordinate, tipi, stringhe e azione.
- Messaggio astratto `{action, params}` inviato tramite `send_to_gev`.
- Nessun commit hash per questa modifica; non attribuire a `bbdcff8`.

## Test e problemi

Test: non eseguiti. Nel wrapper UI letto non esiste `send_to_gev` (`ui.py:4156-4332`); il protocollo GEV embed usa `gev:view` con schema `{id, view}` (`src/app/embed.js:1-8`). Non è documentato né verificato un adattatore fra i due protocolli.

> Da verificare: commit della modifica, implementazione del bridge, mappatura delle azioni e test di validazione/dispatch.

