# Decisioni architetturali e ipotesi

Ogni riga distingue quanto è verificato nel codice/storia da motivazioni ricostruite. Dove non esiste un razionale esplicito, non viene attribuito agli autori.

| Decisione/tema | Stato e motivazione verificata | Alternativa non adottata o non dimostrata | Riferimento |
|---|---|---|---|
| Opzione C: embed + postMessage + MCP | **Ipotesi/proposta**, non decisione storica verificata. GEV supporta embed con messaggi `gev:view`/`gev:ready` e fornisce MCP (`src/app/embed.js:1-20`; `package.json:51`). Non esiste prova che Jarvis li integri. | Finestra browser esterna o solo HTTP verso Vite: alternative non registrate. | GEV `src/app/embed.js:1-20`; Jarvis `ui.py:21-34`; > Da verificare |
| PyQt6 come framework UI | **Verificato**: Jarvis usa PyQt6 e il commit 949 pinna PyQt6 e QtWebEngine. Motivo di mantenere Qt: **ipotesi**, coerente col codice esistente. | Toolkit sostitutivo non compare in storia. WebEngine è in requirements ma uso effettivo non dimostrato. | `949e2ed114f83bf067ad9f1afbfde42a788e8835`; Jarvis `ui.py:21-34`, `requirements.txt:1-2` |
| Node portatile | **Verificato**: `gev_plugin` imposta `.node` nel PATH e controlla il percorso risolto del binario. Il commit descrive runtime portatile. | Node di sistema: non scelto per questo launcher; confronto motivazionale dettagliato **ipotesi**. | `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e`; `plugins/gev_plugin.py:155-174` |
| `node.exe` diretto invece di `npm.cmd` | **Verificato**: usa `node.exe npm-cli.js` per install e `node.exe vite.js` per Vite. `docs/GEV_INTEGRATION.md` esplicita che npm.cmd e il Node figlio sarebbero bloccati dai guardrail. | Invocazione npm wrapper scartata nel documento di integrazione. | `bbdcff8`; `docs/GEV_INTEGRATION.md:38-49`; `plugins/gev_plugin.py:284-337` |
| Windows Job Object con kill-on-close | **Verificato**: assegna il processo a Job Object e usa `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Commit e doc lo legano al cleanup dei discendenti. | Solo `atexit` è mantenuto come fallback, insufficiente per terminazioni forzate secondo doc. | `bbdcff8`; `plugins/gev_plugin.py:183-265`; `docs/GEV_INTEGRATION.md:51-60` |
| `_plugins_stopped_evt` è `threading.Event` | **Verificato**: creato nell'inizializzazione per evitare stop lifecycle ripetuti; set prima di `stop_all`. | Altro primitive/event loop signal non registrato. | `29c198de07ecbabbce95674d6028e7be5f3cc5d9`; `main.py:931-940`, `:1431-1434`, `:2268-2274` |
| Cancellazione task tramite `call_soon_threadsafe` | **Verificato**: runner coordina la cancellazione dell'async task dal thread UI/chiusura. | Cancellazione diretta cross-thread sarebbe alternativa non sicura; il commit registra `call_soon_threadsafe`. | `29c198d`; `main.py:2276-2310` |
| Whitelist `node.exe` nei guardrail | **Verificato**: `node` e `node.exe` entrano nella allowlist per avviare GEV. La documentazione segnala che l'autorizzazione si applica a qualsiasi invocazione subprocess Jarvis; il plugin verifica il path portatile. | Allowlist per directory/caller non risulta implementata. | `4ecff3ac647ce8f311b47cf7045f1d3915be44ae`; `core/guardrails.py:23-33`; `docs/GEV_INTEGRATION.md:26-36` |
| Lifecycle hook nel plugin loader | **Verificato**: hook opzionali `start` e `stop`; avvio ordinato, arresto inverso con timeout globale. | Stop parallelizzato non adottato; la documentazione annota il limite `max_workers=1`. | `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8`; `core/plugin_loader.py:48-88`; `docs/GEV_INTEGRATION.md:1-16` |

## Sintesi

La sequenza embed + postMessage + MCP è tecnicamente compatibile con capacità presenti in GEV, ma l'interfaccia Jarvis non ha ancora il collegamento corrispondente nel codice osservato. Va trattata come proposta, non come decisione approvata. Il razionale degli altri punti è documentato solo dove indicato sopra.

