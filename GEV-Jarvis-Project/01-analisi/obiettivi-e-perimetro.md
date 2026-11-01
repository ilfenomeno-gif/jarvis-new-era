# Obiettivi e perimetro

## Obiettivo verificabile

Integrare l'avvio e l'arresto del server locale God's Eye View nel lifecycle dei plugin di Jarvis, usando un runtime Node portatile e un controllo di salute HTTP. Il plugin dichiara inoltre azioni GEV; nella versione committata la funzione `run()` è un placeholder, mentre un dispatcher esiste solo nel diff locale non committato. Riferimenti: commit `bbdcff8`; Jarvis `plugins/gev_plugin.py:269-398` e diff `git diff -- plugins/gev_plugin.py`.

## Dentro lo scope attestato

- Dipendenze UI PyQt6 e QtWebEngine pin (`requirements.txt:1-2`, commit `949e2ed`).
- Lifecycle hook opzionali del plugin e start/stop ordinato (`core/plugin_loader.py:48-88`, commit `a57413b`).
- Integrazione shutdown/cancellazione task nel runner (`main.py:931-940`, `:2268-2310`, commit `29c198d`).
- Consenso guardrail per `node.exe`, con controllo path nel plugin (`core/guardrails.py:23-33`; `plugins/gev_plugin.py:155-174`, commit `4ecff3a`).
- Avvio di Vite su loopback porta 4173, primo install se `node_modules` assente, health check e stop (`plugins/gev_plugin.py:269-398`).
- GEV come web app Cesium e disponibilità di embed e MCP nel suo repo (`package.json:2-5`, `:51`, `src/app/embed.js:1-20`).

## Fuori scope o non verificato

- Integrazione effettiva della WebView PyQt6, bridge JavaScript/Python o protocollo MCP Jarvis↔GEV: **> Da verificare**. In `ui.py:21-34` non compare QWebEngine; nel wrapper `ui.py:4156-4332` non compare un metodo `send_to_gev`.
- Test end-to-end completati o metriche raggiunte: **> Da verificare**.
- Comportamento dettagliato della voce/strumenti GEV dopo la modifica locale non committata: **> Da verificare**.
- 4c, 4d e passi 5–9: **> Da verificare**, non dedotti dal numero dei commit.
- Branch di rilascio, packaging `.node`, download automatizzato, target di latenza o policy finale MCP: **> Da verificare**.

## Distinzione fra fatto e ipotesi

**Verificato nel codice/storia**: quanto elencato sopra con `path:line` o hash. **Ipotesi**: che lo scopo finale sia un'interfaccia GEV incorporata con controllo vocale di layer/tracking; i nomi delle azioni appaiono nello schema locale ma non provano il completamento del flusso. Riferimenti: Jarvis `plugins/gev_plugin.py:38-85` e working-tree diff.

