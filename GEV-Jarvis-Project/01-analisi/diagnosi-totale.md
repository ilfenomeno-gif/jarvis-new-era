# Diagnosi totale

## Fonti e affidabilità

La fotografia usa Jarvis `feat/gev-integration` a `bbdcff8` più un diff locale in `plugins/gev_plugin.py`, e GEV `feat/gev-integration` a `aa16b7c`. I riferimenti `path:line` sono relativi alla root del repository indicata nel [README](../README.md). Il codice GEV è letto dal checkout locale, non assunto uguale a un remoto.

## GEV: architettura rilevante

- GEV è dichiarato in `package.json` come app browser, versione 0.2.1, con Cesium e Vite (`package.json:2-5`, `:34-52`, `:57-71`).
- Esiste una modalità embed `?embed=1` e un protocollo di messaggi `gev:view`, `gev:view-applied`, `gev:ready` (`src/app/embed.js:1-20`, `:31-45`). Il modulo attende messaggi di visualizzazione dal parent secondo il contratto commentato e implementato nel resto del file (`src/app/embed.js:1-12`).
- È presente codice MCP (`src/tools/mcp/index.js:1-9`, `src/tools/mcp/http.js:1-13`) e lo script `mcp` in `package.json:51`; questo non prova che Jarvis lo usi.
- Il package richiede Node `>=24.14.0 <25 || >=26 <27` (`package.json:17-19`).

## Jarvis: architettura rilevante

- La UI usa PyQt6 Core/Gui/Widgets (`ui.py:21-34`) e `JarvisUI` istanzia `QApplication` e `MainWindow` (`ui.py:4156-4162`). `requirements.txt` pinna anche PyQt6-WebEngine 6.11.0 (`requirements.txt:1-2`), ma l'import UI osservato non include `QWebEngineView`.
- `JarvisLive.__init__` scopre i plugin, crea eventi di shutdown e avvia `start_all` su thread daemon (`main.py:925-941`). `run()` conserva il task/event loop e controlla l'evento shutdown (`main.py:2065-2069`, `:2103-2107`).
- Il plugin loader avvia gli hook nell'ordine di discovery e ferma gli hook in ordine inverso, con timeout globale (`core/plugin_loader.py:48-88`).
- Il plugin `gev` avvia Node portatile, installa dipendenze se manca `node_modules`, lancia Vite su loopback 4173 e controlla l'health URL (`plugins/gev_plugin.py:155-174`, `:269-373`). Il `stop()` fa terminate/kill e chiude il Job Object (`:135-152`, `:377-398`).

## Punti di contatto realmente presenti

Il loader scopre `plugins/gev_plugin.py`; il lifecycle viene avviato in background dall'inizializzazione di `JarvisLive` e fermato in shutdown (`main.py:925-941`, `:2268-2274`). La whitelist permette `node` e `node.exe` (`core/guardrails.py:23-33`). La documentazione d'integrazione spiega il rischio di autorizzazione ampia e la verifica del percorso Node (`docs/GEV_INTEGRATION.md:18-49`).

Nel diff non committato il dispatcher valida cinque azioni (`plugins/gev_plugin.py:401-463`) e cerca `player.send_to_gev` (`:464-471`). Nella UI pubblica letta sono esposti logging, widgets e altri metodi, ma non `send_to_gev` (`ui.py:4156-4332`); la ricerca dei riferimenti non ha individuato un bridge Jarvis->GEV. Questo è un riscontro sul checkout esaminato, non una prova su revisioni future.

## Problemi aperti osservabili

1. Il dispatcher è solo working-tree e non ha hash commit (`git diff -- plugins/gev_plugin.py`).
2. Il contratto GEV embed usa `gev:view` con shape `{id, view}`; il dispatcher locale usa oggetti `{action, params}` e non è dimostrata la trasformazione fra i due (`src/app/embed.js:1-8`; diff locale `plugins/gev_plugin.py`).
3. Non è stato trovato `send_to_gev` nella classe UI osservata (`ui.py:4156-4332`).
4. `tests/test_plugin_lifecycle.py` non esiste; nella directory tests è presente `test_writing_assistant.py` soltanto.
5. Il lifecycle timeout globale non può interrompere un hook già in esecuzione, come documentato (`docs/GEV_INTEGRATION.md:1-16`).
6. La presenza e versione effettiva del runtime `.node` non sono state eseguite/verificate; `.node/` è non tracciata in GEV (`git status --short`) e `git check-ignore -v -- .node .node/node.exe` non la identifica come ignorata. Il `.gitignore` letto contiene una regola per `node_modules`, non per `.node` (`.gitignore:1`).
7. Non sono state eseguite prove di start/stop, health check, embed, dispatcher o orfani.

Ulteriori priorità e ipotesi sono riportate in [debito tecnico](../06-debito-tecnico/debito-tecnico.md). Niente in questa diagnosi dimostra che l'integrazione voce/UI sia end-to-end.
