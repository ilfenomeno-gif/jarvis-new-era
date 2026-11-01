# Debito tecnico

Priorità e impatto sono valutazioni di archivio. Le voci chiuse indicano codice presente, non test passato.

## Aperto

| Area | Debito | Impatto | Priorità | Riferimento |
|---|---|---|---|---|
| UI bridge | Il dispatcher locale chiama `send_to_gev`, non presente nel wrapper `JarvisUI` osservato | Le azioni non hanno un trasporto dimostrato | P0 | Diff locale `plugins/gev_plugin.py`; `ui.py:4156-4332` |
| Protocollo | GEV embed documenta `{type:'gev:view', id, view}` mentre il dispatcher prepara `{action, params}` | Serve mappatura e gestione reply | P0 | GEV `src/app/embed.js:1-8`; diff locale |
| Test | Non c'è `tests/test_plugin_lifecycle.py` | Nessuna regressione automatica per ordine/errore/timeout | P1 | Listing `tests`; `core/plugin_loader.py:48-88` |
| Runtime | `.node/` non tracciata; origine e versione non validate | Start dipende dallo stato macchina locale | P1 | `git status` GEV; Jarvis `plugins/gev_plugin.py:155-174` |
| Validazione | Nessun test GEV startup, shutdown o process orphan eseguito in questa raccolta | Rischio lifecycle non misurato | P1 | `plugins/gev_plugin.py:269-398`; test plan in `04-test/` |
| Metriche | p95, copertura e tempi non raccolti; timeout non equivale a target prestazionale | Nessun criterio quantitativo di accettazione | P2 | `plugins/gev_plugin.py:23-25`; `04-test/metriche.md` |
| Versione Node | Procedura richiesta punta a 24.x, ma package supporta anche 26.x | Possibile disallineamento fra target deployment e upstream | P2 | GEV `package.json:17-19` |
| Scope whitelist | `node.exe` è autorizzato per subprocess di qualsiasi componente Jarvis | Aumenta la superficie autorizzata | P1 | `docs/GEV_INTEGRATION.md:26-36` |
| Timeout stop | Un hook già in esecuzione non può essere cancellato dal Future | Thread può proseguire in background | P2 | `core/plugin_loader.py:69-88`; `docs/GEV_INTEGRATION.md:1-16` |

## Chiuso nel codice (test ancora da verificare)

| Area | Debito risolto nel codice | Impatto mitigato | Priorità | Riferimento |
|---|---|---|---|---|
| Requirements | Versioni Qt fissate a 6.11.0 | Ambiente più deterministico | Chiuso | `949e2ed114f83bf067ad9f1afbfde42a788e8835`; `requirements.txt:1-2` |
| Lifecycle | Start/stop hook, ordine inverso e isolamento eccezioni | Plugin con risorse gestibili | Chiuso | `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8`; `core/plugin_loader.py:48-88` |
| Shutdown | Eventi e cancellazione task thread-safe | Coordinamento stop | Chiuso | `29c198de07ecbabbce95674d6028e7be5f3cc5d9`; `main.py:2268-2310` |
| Guardrail | Binario Node consentito e path runtime verificato nel plugin | Avvio locale GEV possibile, con limitazione plugin | Chiuso nel codice | `4ecff3a`; `bbdcff8`; `core/guardrails.py:23-33`; `plugins/gev_plugin.py:155-174` |
| Processo GEV | Stop terminate/kill e Windows Job Object | Riduce rischio di child Node orfani | Chiuso nel codice | `bbdcff8`; `plugins/gev_plugin.py:135-152`, `:183-265`, `:377-398` |

