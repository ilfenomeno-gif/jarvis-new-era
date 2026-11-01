# Passo 4a — Lifecycle del plugin GEV

## Obiettivo

Avviare il server Vite locale con Node portatile, attendere una risposta e terminare il processo in modo controllato.

## File toccati e commit

- `plugins/gev_plugin.py`
- `docs/GEV_INTEGRATION.md`
- Commit `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e` — `feat(plugins): gev_plugin lifecycle with portable Node runtime`.

## Modifiche chiave

`GEV_DIR`, `.node`, porta 4173, health URL e timeout sono definiti in `plugins/gev_plugin.py:19-26`. `_gev_runtime()` verifica percorso Node e npm CLI (`:155-174`). `start()` rifiuta una porta già occupata, lancia install se manca `node_modules`, quindi avvia `node.exe ...vite.js --host 127.0.0.1 --port 4173 --strictPort` e verifica risposta HTTP 200 (`:269-373`). Job Object e kill-on-close: `:183-265`. Stop terminate/kill: `:377-398`.

## Test e note

Output test: nessun test di avvio o stop eseguito. `STARTUP_TIMEOUT_SEC=60`, `INSTALL_TIMEOUT_SEC=600`, `STOP_TIMEOUT_SEC=5` sono limiti configurati, non misure di prestazione (`:23-25`).

Il commit descrive anche `atexit` e Job Object (`docs/GEV_INTEGRATION.md:51-60`). Lo schema committed dichiara azioni placeholder, non prova un dispatcher funzionante (`plugins/gev_plugin.py:38-85` al commit).

> Da verificare: primo avvio, secondo avvio, health endpoint e process tree su Windows.

