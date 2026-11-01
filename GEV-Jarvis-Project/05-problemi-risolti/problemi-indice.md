# Indice problemi e rilievi

La storia Git documenta quattro cambiamenti di integrazione e un pin dipendenze; non contiene una lista storica di 13 ticket. Le voci aperte qui sotto sono rilievi direttamente verificabili, non affermazioni che siano stati tutti “incontrati” come incidenti. Gravità = valutazione archivistica, non classificazione presente nei commit.

| ID | Descrizione | Gravità | Risoluzione/stato | Riferimento |
|---|---|---|---|---|
| P01 | Versioni Qt non fissate nel requirements precedente | Bassa | Pin di PyQt6 e QtWebEngine 6.11.0 | `949e2ed114f83bf067ad9f1afbfde42a788e8835`; `requirements.txt:1-2` |
| P02 | Loader non aveva hook lifecycle start/stop | Media | Aggiunti `start_all` e `stop_all` | `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8`; `core/plugin_loader.py:48-88` |
| P03 | Chiusura Jarvis non coordinava gli hook plugin | Alta | Eventi, `finally`, thread join/cancellazione thread-safe | `29c198de07ecbabbce95674d6028e7be5f3cc5d9`; `main.py:931-940`, `:2268-2310` |
| P04 | Guardrail bloccava Node per avvio locale GEV | Alta | Allowlist `node`/`node.exe`; scope ampio documentato | `4ecff3ac647ce8f311b47cf7045f1d3915be44ae`; `core/guardrails.py:23-33` |
| P05 | `npm.cmd` non era invocabile dal launcher guarded | Media | Node diretto con npm-cli.js e vite.js | `bbdcff8`; `docs/GEV_INTEGRATION.md:38-49` |
| P06 | Il solo stop Python non copre ogni uscita abrupt | Alta | Job Object kill-on-close; `atexit` come fallback | `bbdcff8`; `plugins/gev_plugin.py:183-265`; `docs/GEV_INTEGRATION.md:51-60` |
| P07 | Runtime di sistema potrebbe risolvere un binario diverso | Alta | Controllo del percorso risolto contro `.node/node.exe` | `bbdcff8`; `plugins/gev_plugin.py:155-174` |
| P08 | Primo avvio può non avere `node_modules` | Media | `npm install` eseguito condizionalmente con timeout/output | `bbdcff8`; `plugins/gev_plugin.py:287-311` |
| P09 | Vite potrebbe non diventare pronto | Media | Poll health HTTP fino a timeout, errori raccolti | `bbdcff8`; `plugins/gev_plugin.py:347-373` |
| P10 | Porta locale già usata non deve far terminare un processo estraneo | Alta | Conflitto rilevato e sollevata eccezione prima del launch | `bbdcff8`; `plugins/gev_plugin.py:279-282` |
| P11 | Stop hook bloccato non è cancellabile se già in esecuzione | Media | Limite documentato; non risolto dal loader seriale | `docs/GEV_INTEGRATION.md:1-16`; `core/plugin_loader.py:69-88` |
| P12 | Manca il test lifecycle richiesto | Media | Aperto: `tests/test_plugin_lifecycle.py` non trovato | listing `tests` e `Test-Path` durante raccolta |
| P13 | `send_to_gev` cercato dal dispatcher non è esposto dal wrapper UI osservato | Alta | Aperto; bridge da verificare/implementare | diff locale `plugins/gev_plugin.py`; `ui.py:4156-4332` |

“Risolto” nei casi P01–P10 significa che esiste una modifica o salvaguardia nel codice/storia, non che la relativa regressione sia stata collaudata in runtime.

